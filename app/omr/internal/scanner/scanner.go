package scanner

import (
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"io"
	"ubco-team15/omr/internal/sys"

	"gocv.io/x/gocv"
	"golang.org/x/sync/errgroup"
)

// QualityError marks a failure caused by the scanned image itself — too
// small, corrupt, misaligned, or too skewed/faint to find its anchors —
// rather than a bug or bad template config. Callers use errors.As to tell
// "ask for a rescan" apart from "something broke on our end".
type QualityError struct {
	msg string
}

func (e *QualityError) Error() string { return e.msg }

func newQualityError(format string, args ...any) error {
	return &QualityError{msg: fmt.Sprintf(format, args...)}
}

// OrderError marks a failure where a page didn't match the anchors of its
// expected slot but did match a different page in the template — evidence
// that the pages were fed in the wrong order (e.g. the back page scanned
// first), rather than a generic scan-quality problem. Callers use errors.As
// to give a more specific "check your page order" message than a plain
// QualityError would.
type OrderError struct {
	PageIndex         int
	DetectedPageIndex int
}

func (e *OrderError) Error() string {
	return fmt.Sprintf(
		"page %d does not match its expected layout, but matches page %d instead — pages may be out of order",
		e.PageIndex, e.DetectedPageIndex,
	)
}

type ScanData struct {
	// The picture of a scan is only partially processed. It will be aligned
	// and scaled to have the same coordinate system as the "Binary" version,
	// but it will not be fully binarized. The "picture" is only meant for
	// human viewing; all further marking/processing should be done on the
	// binary matrix.
	Picture gocv.Mat
	Binary  gocv.Mat
}

func (d *ScanData) Close() {
	d.Picture.Close()
	d.Binary.Close()
}

func (d *ScanData) Empty() bool {
	return d.Picture.Empty() || d.Binary.Empty()
}

type Anchor struct {
	Image  *gocv.Mat       `json:"-"`
	Path   string          `json:"path"`
	ROI    image.Rectangle `json:"roi"`
	Center image.Point     `json:"center"`
}

func (a *Anchor) Close() {
	a.Image.Close()
}

// ScanPage holds the anchor markers for a single exam page.
type ScanPage struct {
	Anchors []Anchor `json:"anchors"`
}

// Template is the scan template for a multi-page exam. Each entry in Pages
// describes one physical page with its own set of anchor markers. Single-page
// exams use a Pages array with one entry.
type Template struct {
	Width  int        `json:"width"`
	Height int        `json:"height"`
	Pages  []ScanPage `json:"pages"`
	Config Config     `json:"config"`
	// NativeDpi is the resolution the template's Width/Height/anchor
	// positions were authored at. Zero means unknown (older templates that
	// predate this field). Callers use it to request matching-resolution
	// renders instead of guessing a fixed DPI.
	NativeDpi float64 `json:"nativeDpi,omitempty"`
}

func (t *Template) Close() {
	for pi := range t.Pages {
		for i := range t.Pages[pi].Anchors {
			t.Pages[pi].Anchors[i].Image.Close()
		}
	}
}

type Config struct {
	BlurSize            int     `json:"blurSize"`
	MorphCloseSize      int     `json:"morphCloseSize"`
	MinAnchorConfidence float32 `json:"minAnchorConfidence"`
	// AdaptiveBlockSize is the neighbourhood size for adaptive thresholding
	// (must be odd). Defaults to 91, which works well for 200–300 DPI scans.
	AdaptiveBlockSize int `json:"adaptiveBlockSize"`
	// AdaptiveC is subtracted from the local mean; negative values make the
	// threshold more lenient and are needed to catch light pencil marks.
	AdaptiveC float32 `json:"adaptiveC"`
	// ReferenceRatio is the imgSize/templateSize ratio (see sizeRatio) that
	// BlurSize/AdaptiveBlockSize/MorphCloseSize above were tuned against,
	// i.e. what a scan at the template's intended calibration DPI produces.
	// Zero means unknown, in which case preprocessPage leaves these values
	// unscaled regardless of the actual scan's resolution (the pre-existing
	// behavior, kept for templates authored before this field existed).
	ReferenceRatio float64 `json:"referenceRatio,omitempty"`
}

// Scan runs each reader through the OMR preprocessing pipeline using the
// corresponding page's anchors from tmpl. The number of readers must match
// len(tmpl.Pages). Each returned ScanData must be closed by the caller.
func Scan(readers []io.Reader, tmpl *Template) ([]*ScanData, error) {
	n := len(tmpl.Pages)
	if len(readers) != n {
		return nil, fmt.Errorf("template has %d page(s), got %d image(s)", n, len(readers))
	}
	results := make([]*ScanData, n)

	wg := errgroup.Group{}
	for i, r := range readers {
		wg.Go(func() (err error) {
			defer func() {
				if r := recover(); r != nil {
					err = fmt.Errorf("page %d: panic: %v", i, r)
				}
			}()

			buf, err := io.ReadAll(r)
			if err != nil {
				return fmt.Errorf("page %d: %w", i, err)
			}
			data, err := scanPage(buf, tmpl, i)
			if err != nil {
				return fmt.Errorf("page %d: %w", i, err)
			}
			results[i] = data
			return nil
		})
	}
	if err := wg.Wait(); err != nil {
		for i := range results {
			if results[i] != nil {
				results[i].Close()
			}
		}
		return nil, err
	}

	return results, nil
}

// scanPage runs a single reader through the preprocessing pipeline using the
// anchors for page idx.
func scanPage(buf []byte, tmpl *Template, idx int) (*ScanData, error) {

	img, err := gocv.IMDecode(buf, gocv.IMReadGrayScale)
	if err != nil {
		return nil, newQualityError("decode: %s", err.Error())
	}

	if img.Empty() {
		img.Close()
		return nil, newQualityError("decoded image is empty")
	}

	if img.Cols() <= 100 || img.Rows() <= 100 {
		img.Close()
		return nil, newQualityError("image dimensions too small: %dx%d", img.Cols(), img.Rows())
	}

	data, err := preprocessPage(img, tmpl, idx)
	if err != nil {
		var qerr *QualityError
		if !errors.As(err, &qerr) {
			return nil, err
		}
		if detected, ok := detectMisplacedPage(data, tmpl, idx); ok {
			data.Close()
			return nil, &OrderError{PageIndex: idx, DetectedPageIndex: detected}
		}
		data.Close()
		return nil, fmt.Errorf("preprocessing pipeline failed: %w", err)
	}

	return data, nil
}

// dpiMismatchLowRatio and dpiMismatchHighRatio bound how far a scanned
// page's resolution can drift from its template's calibration size before
// it's logged as a likely cause of degraded confidence, rather than staying
// a silent side effect of scaleConfig/scaleAnchorTemplate's resizing.
const (
	dpiMismatchLowRatio  = 0.67
	dpiMismatchHighRatio = 1.5
)

// preprocessPage binarizes and warps picture against tmpl's anchors for
// page idx, retrying upside-down once if the initial match fails. Before
// binarizing, conf's pixel-based tuning (BlurSize, AdaptiveBlockSize,
// MorphCloseSize) is scaled by picture's resolution relative to the
// template's calibration size, so a scan captured well above or below the
// template's native DPI still binarizes with a physically consistent
// neighbourhood instead of one tuned for a different resolution.
//
// On success picture is owned by the returned ScanData. On an unrecoverable
// error picture is closed and the returned error already describes the
// pipeline failure. If, after the upside-down retry, warp is still unable
// to align the page, the still-open ScanData is returned alongside the raw
// *QualityError so the caller can attempt further recovery (e.g. page-order
// detection) before closing it.
func preprocessPage(picture gocv.Mat, tmpl *Template, idx int) (*ScanData, error) {
	data := &ScanData{Picture: picture, Binary: gocv.NewMat()}

	ratio := sizeRatio(
		image.Pt(picture.Cols(), picture.Rows()),
		image.Pt(tmpl.Width, tmpl.Height),
	)

	// scaleFactor is how far ratio has drifted from the ratio the template's
	// Binarize tuning was actually calibrated against (ReferenceRatio),
	// not from 1.0. A template's Width/Height is just an internal working
	// resolution decoupled from any real scan DPI, and BlurSize/
	// AdaptiveBlockSize/MorphCloseSize have historically been tuned against
	// whatever DPI the upload pipeline requests (e.g. ~1.4x the template's
	// own canvas size at the OMR service's 216 DPI default), not against a
	// scan that happens to match the canvas 1:1. Without a known
	// ReferenceRatio there's nothing to scale relative to, so scaleFactor
	// stays 1 (the pre-existing, unscaled behavior).
	scaleFactor := 1.0
	if tmpl.Config.ReferenceRatio > 0 {
		scaleFactor = ratio / tmpl.Config.ReferenceRatio
	}
	if scaleFactor < dpiMismatchLowRatio || scaleFactor > dpiMismatchHighRatio {
		sys.Warn(
			"scanned page resolution deviates significantly from template calibration",
			"scaleFactor", scaleFactor,
			"observedRatio", ratio,
			"referenceRatio", tmpl.Config.ReferenceRatio,
			"templateWidth", tmpl.Width,
			"templateHeight", tmpl.Height,
			"imageWidth", picture.Cols(),
			"imageHeight", picture.Rows(),
		)
	}

	scaledConf := scaleConfig(tmpl.Config, scaleFactor)
	if err := Binarize(&data.Picture, &data.Binary, &scaledConf); err != nil {
		data.Close()
		return nil, fmt.Errorf("preprocessing pipeline failed: %w", err)
	}

	err := warp(
		data, data,
		tmpl.Pages[idx].Anchors,
		tmpl.Width,
		tmpl.Height,
		tmpl.Config,
	)
	if err == nil {
		return data, nil
	}

	var qerr *QualityError
	if !errors.As(err, &qerr) {
		data.Close()
		return nil, fmt.Errorf("preprocessing pipeline failed: %w", err)
	}

	if rotErr := recoverUpsideDown(data, tmpl.Pages[idx].Anchors, tmpl); rotErr != nil {
		return data, err
	}

	return data, nil
}

// sizeRatio is the average of src's width and height ratios to target, i.e.
// how much bigger (>1) or smaller (<1) src is than the template's
// calibration size. Anchor positions and pixel-based tuning parameters are
// all defined in that target coordinate space, so this is the single factor
// needed to scale a scalar tuning value (as opposed to scaleROI/
// scaleAnchorTemplate, which scale per-axis geometry and so keep X and Y
// separate).
func sizeRatio(src, target image.Point) float64 {
	return (float64(src.X)/float64(target.X) + float64(src.Y)/float64(target.Y)) / 2
}

// scaleConfig scales conf's pixel-based tuning (BlurSize, AdaptiveBlockSize,
// MorphCloseSize) by ratio so binarization stays physically consistent
// regardless of the scanned image's resolution relative to the template's
// calibration size. MinAnchorConfidence and AdaptiveC are already
// resolution-independent and are left untouched.
func scaleConfig(conf Config, ratio float64) Config {
	scaled := conf
	// Zero-valued fields are left untouched: BlurSize=0 is invalid input
	// Binarize rejects on its own, and AdaptiveBlockSize=0 means "use
	// Binarize's built-in default", neither of which should silently turn
	// into a scaled real value here.
	if conf.BlurSize > 0 {
		scaled.BlurSize = scaleOddSize(conf.BlurSize, ratio, 1)
	}
	if conf.AdaptiveBlockSize > 0 {
		scaled.AdaptiveBlockSize = scaleOddSize(conf.AdaptiveBlockSize, ratio, 3)
	}
	if conf.MorphCloseSize > 0 {
		scaled.MorphCloseSize = scaleSize(conf.MorphCloseSize, ratio, 0)
	}
	return scaled
}

// scaleSize scales size by ratio, rounding to the nearest integer no
// smaller than min.
func scaleSize(size int, ratio float64, min int) int {
	scaled := int(float64(size)*ratio + 0.5)
	if scaled < min {
		scaled = min
	}
	return scaled
}

// scaleOddSize is scaleSize but rounded up to the nearest odd value
// afterwards, since GaussianBlur and AdaptiveThreshold both require an odd
// neighbourhood size.
func scaleOddSize(size int, ratio float64, min int) int {
	scaled := scaleSize(size, ratio, min)
	if scaled%2 == 0 {
		scaled++
	}
	return scaled
}

// recoverUpsideDown retries the anchor match against a copy of data rotated
// 180°: a page fed in upside-down moves every anchor out of its expected
// ROI, which warp's own ±5° skew tolerance can't recover from, so the whole
// frame needs to be rotated back before re-matching. On success it replaces
// data's Picture/Binary with the corrected, warped result in place. On
// failure data is left untouched and the caller should report the original
// error.
func recoverUpsideDown(
	data *ScanData,
	anchors []Anchor,
	tmpl *Template,
) error {
	rotated := &ScanData{Picture: gocv.NewMat(), Binary: gocv.NewMat()}
	defer rotated.Close()

	err := gocv.Rotate(data.Picture, &rotated.Picture, gocv.Rotate180Clockwise)
	if err != nil {
		return err
	}

	err = gocv.Rotate(data.Binary, &rotated.Binary, gocv.Rotate180Clockwise)
	if err != nil {
		return err
	}

	err = warp(
		rotated, rotated,
		anchors,
		tmpl.Width, tmpl.Height,
		tmpl.Config,
	)
	if err != nil {
		return err
	}

	data.Close()
	data.Picture = rotated.Picture
	data.Binary = rotated.Binary
	rotated.Picture = gocv.NewMat()
	rotated.Binary = gocv.NewMat()
	return nil
}

// detectMisplacedPage checks data — in both its original and 180°-rotated
// orientation — against every other page's anchors. warp doesn't care whose
// anchors it's given, so this is the same match already used for idx, just
// aimed at the rest of the template. A match on another page is strong
// evidence this image was fed into the wrong slot, and reports which page
// it actually looks like.
func detectMisplacedPage(
	data *ScanData,
	tmpl *Template,
	idx int,
) (detected int, ok bool) {

	rotated := &ScanData{Picture: gocv.NewMat(), Binary: gocv.NewMat()}
	defer rotated.Close()

	rotatedOK :=
		gocv.Rotate(data.Picture, &rotated.Picture, gocv.Rotate180Clockwise) == nil &&
			gocv.Rotate(data.Binary, &rotated.Binary, gocv.Rotate180Clockwise) == nil

	probe := &ScanData{Picture: gocv.NewMat(), Binary: gocv.NewMat()}
	defer probe.Close()

	for j := range tmpl.Pages {
		if j == idx {
			continue
		}

		otherAnchors := tmpl.Pages[j].Anchors

		err := warp(
			data,
			probe,
			otherAnchors,
			tmpl.Width, tmpl.Height,
			tmpl.Config,
		)
		if err == nil {
			return j, true
		}

		err = warp(
			rotated,
			probe,
			otherAnchors,
			tmpl.Width, tmpl.Height,
			tmpl.Config,
		)
		if rotatedOK && err == nil {
			return j, true
		}
	}

	return 0, false
}

// Note: the given matrix must be in grayscale.
func Binarize(src, dst *gocv.Mat, conf *Config) error {

	//
	// Handle bad inputs and set defaults.
	//

	switch {
	case src.Empty():
		return fmt.Errorf("cannot binarize an empty image")
	case conf.BlurSize%2 == 0:
		return fmt.Errorf("blurSize must be odd, got %d", conf.BlurSize)
	}

	blockSize := conf.AdaptiveBlockSize
	if blockSize == 0 {
		blockSize = 91
	}

	adaptiveC := conf.AdaptiveC
	if adaptiveC == 0 {
		adaptiveC = -15.0
	}

	//
	// Adjust the block size to be smaller than the minimum dimension size of
	// the image. Block sizes that don't fit inside the target image are
	// inefficient and, in extreme cases, degrade performance. We then have to
	// ensure that the adjusted value is still valid (i.e., that it is odd and
	// positive. Like Weird Al Yankovic.)
	//

	blockSize = min(blockSize, src.Rows(), src.Cols())
	if blockSize%2 == 0 {
		blockSize--
	}
	if blockSize < 3 {
		blockSize = 3
	}

	//
	// Run through the binarization pipeline. The steps are as follows:
	//
	// 1) Blur the image.
	//
	// 2) Use adaptive thresholding to binarize the image.
	//    <https://docs.opencv.org/4.12.0/d7/d1b/group__imgproc__misc.html#ga72b913f352e4a1b1b397736707afcde3>
	//
	// 3) Use a morphological close to close small gaps and make the lines
	//    nicer.
	//    <https://docs.opencv.org/4.12.0/d4/d86/group__imgproc__filter.html#ga67493776e3ad1a3df63883829375201f>
	//

	var (
		blur   = gocv.NewMat()
		thresh = gocv.NewMat()
		kernel = gocv.GetStructuringElement(
			gocv.MorphRect,
			image.Pt(conf.MorphCloseSize, conf.MorphCloseSize),
		)
	)
	defer blur.Close()
	defer thresh.Close()
	defer kernel.Close()

	gocv.GaussianBlur(
		*src, &blur,
		image.Pt(conf.BlurSize, conf.BlurSize),
		0, 0,
		gocv.BorderDefault,
	)
	gocv.AdaptiveThreshold(
		blur, &thresh,
		255,
		gocv.AdaptiveThresholdMean,
		gocv.ThresholdBinaryInv,
		blockSize,
		adaptiveC,
	)
	gocv.MorphologyEx(
		thresh, dst,
		gocv.MorphClose,
		kernel,
	)

	return nil
}

func warp(src, dst *ScanData, anchors []Anchor, width, height int, conf Config) error {
	if src.Empty() {
		return fmt.Errorf("cannot warp an empty image")
	}
	if len(anchors) < 3 {
		return fmt.Errorf("warping requires at least 3 anchors, provided %d", len(anchors))
	}

	for i := range anchors {
		if anchors[i].Image.Empty() {
			return fmt.Errorf("anchor %d: image not loaded, call LoadTemplate first", i)
		}
	}

	n := len(anchors)
	srcPts := make([]image.Point, n)
	dstPts := make([]image.Point, n)

	srcSize := image.Pt(src.Binary.Cols(), src.Binary.Rows())
	targetSize := image.Pt(width, height)

	for i := range n {
		anchor := anchors[i]
		anchor.ROI = scaleROI(anchor.ROI, srcSize, targetSize)

		// Scale the anchor template to the size it occupies in the scanned
		// image before running matchTemplate — template matching is not
		// scale-invariant, so a 24px PNG matched against a ~51px printed anchor
		// (at 300 DPI) produces near-zero confidence scores.
		scaled := scaleAnchorTemplate(anchor.Image, srcSize, targetSize)
		defer scaled.Close()
		anchor.Image = scaled

		pt, err := findAnchorCenter(src.Binary, anchor, conf.MinAnchorConfidence)
		if err != nil {
			return fmt.Errorf("anchor %d: %w", i, err)
		}

		srcPts[i] = pt
		dstPts[i] = anchors[i].Center
	}

	srcPts2f := make([]gocv.Point2f, n)
	dstPts2f := make([]gocv.Point2f, n)
	for i := range n {
		srcPts2f[i] = gocv.Point2f{X: float32(srcPts[i].X), Y: float32(srcPts[i].Y)}
		dstPts2f[i] = gocv.Point2f{X: float32(dstPts[i].X), Y: float32(dstPts[i].Y)}
	}
	srcVec := gocv.NewPoint2fVectorFromPoints(srcPts2f)
	defer srcVec.Close()
	dstVec := gocv.NewPoint2fVectorFromPoints(dstPts2f)
	defer dstVec.Close()

	warped := ScanData{
		Picture: gocv.NewMat(),
		Binary:  gocv.NewMat(),
	}

	// EstimateAffine2D fits a least-squares affine from 3+ point pairs, so
	// additional anchors reduce sensitivity to individual matching errors.
	transform := gocv.EstimateAffine2D(srcVec, dstVec)
	defer transform.Close()
	if transform.Empty() {
		return newQualityError("could not estimate affine transform from anchor points")
	}

	gocv.WarpAffine(src.Picture, &warped.Picture, transform, targetSize)
	gocv.WarpAffine(src.Binary, &warped.Binary, transform, targetSize)

	// Bilinear interpolation produces intermediate gray values at edges; re-snap
	// to strict 0/255 so CountNonZero only counts genuinely filled pixels.
	gocv.Threshold(warped.Binary, &warped.Binary, 128, 255, gocv.ThresholdBinary)

	// Since we are modifying dst in-place,
	// we must close the old mats before overwriting.
	dst.Close()
	dst.Picture = warped.Picture
	dst.Binary = warped.Binary

	return nil
}

func findAnchorCenter(
	binary gocv.Mat,
	anchor Anchor,
	minConfidence float32,
) (image.Point, error) {

	//
	// We run an iterative refining search here:
	//
	// 1) We start by picking a specific middle point and a breadth.
	// 2) We select a few equidistant points in that search area and
	//    iterate over all of them.
	// 3) We take note of the one with the highest value and restart the search
	//    with it as the new middle point, except that breadth has been shrunk
	//    by some factor (the "refining factor").
	//
	// We could use a more sophisticated convex optimization method, but since
	// we can't really guarantee the convex-ness (?) of the objective function
	// I doubt that the risk of falling into a local maximum is worth the
	// marginal performance boost.
	//

	size := image.Pt(anchor.Image.Cols(), anchor.Image.Rows())

	const (
		earlyBreakConfidence = 0.95
		refiningIterations   = 3
		refiningFactor       = 2.0
		anglesPerIteration   = 4
		initialMiddle        = 0.0
		initialBreadth       = 10.0
	)

	var (
		center       = image.Pt(size.X/2, size.Y/2)
		bestValue    float32
		bestLocation image.Point

		middle  = initialMiddle
		breadth = initialBreadth
		angles  = [anglesPerIteration]float64{}
	)

	// Preallocate the matrices.
	var (
		rotated = gocv.NewMat()
		result  = gocv.NewMat()
		roi     = binary.Region(anchor.ROI)
		mask    = gocv.NewMat()
	)
	defer rotated.Close()
	defer result.Close()
	defer roi.Close()
	defer mask.Close()

	for range refiningIterations {

		delta := breadth / float64(anglesPerIteration-1)
		lo := middle - breadth/2
		for i := range angles {
			angles[i] = lo + float64(i)*delta
		}
		bestAngle := middle

		for _, angle := range angles {
			matrix := gocv.GetRotationMatrix2D(center, angle, 1.0)

			gocv.WarpAffine(*anchor.Image, &rotated, matrix, size)
			matrix.Close()

			gocv.MatchTemplate(roi, rotated, &result, gocv.TmCcoeffNormed, mask)
			_, value, _, location := gocv.MinMaxLoc(result)

			if value > bestValue {
				bestValue = value
				bestLocation = location
				bestAngle = angle
			}

			if value > earlyBreakConfidence {
				bestValue = value
				bestLocation = location
				break
			}
		}

		middle = bestAngle
		breadth /= refiningFactor
	}

	if bestValue < minConfidence {
		return image.Point{}, newQualityError(
			"confidence %.2f below threshold %.2f",
			bestValue,
			minConfidence,
		)
	}

	return image.Pt(
		anchor.ROI.Min.X+bestLocation.X+size.X/2,
		anchor.ROI.Min.Y+bestLocation.Y+size.Y/2,
	), nil
}

// scaleAnchorTemplate resizes the anchor PNG to the size it occupies in the
// scanned image (src), given the template coordinate space (target). The caller
// must Close the returned Mat.
func scaleAnchorTemplate(tmpl *gocv.Mat, src, target image.Point) *gocv.Mat {
	newW := int(float64(tmpl.Cols())*float64(src.X)/float64(target.X) + 0.5)
	newH := int(float64(tmpl.Rows())*float64(src.Y)/float64(target.Y) + 0.5)
	if newW < 1 {
		newW = 1
	}
	if newH < 1 {
		newH = 1
	}

	// Shrinking (a lower-DPI scan than the template's calibration) and
	// growing (a higher-DPI scan) fail differently: INTER_AREA antialiases
	// properly when downsampling, avoiding moire that would otherwise blur
	// out the anchor's ring pattern, while linear interpolation is the
	// better choice when upsampling.
	interpolation := gocv.InterpolationLinear
	if newW*newH < tmpl.Cols()*tmpl.Rows() {
		interpolation = gocv.InterpolationArea
	}

	scaled := gocv.NewMat()
	gocv.Resize(*tmpl, &scaled, image.Pt(newW, newH), 0, 0, interpolation)
	return &scaled
}

// ROI coordinates are defined relative to the target image so that they
// can remain resolution independent. This scales their dimensions relative
// to the source image's dimensions before searching.
func scaleROI(roi image.Rectangle, src, target image.Point) image.Rectangle {
	sx := float64(src.X) / float64(target.X)
	sy := float64(src.Y) / float64(target.Y)
	return image.Rect(
		int(float64(roi.Min.X)*sx), int(float64(roi.Min.Y)*sy),
		int(float64(roi.Max.X)*sx), int(float64(roi.Max.Y)*sy),
	)
}

// LoadTemplate parses a template from r and loads anchor images using open.
// open receives each anchor's path as written in the JSON; the caller is
// responsible for resolving relative paths and expanding ~ if needed.
// Both single-page (top-level anchors) and multi-page (pages array) formats
// are supported.
func LoadTemplate(
	r io.Reader, open func(string) (io.ReadCloser, error),
) (*Template, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	var tmpl Template
	if err := json.Unmarshal(data, &tmpl); err != nil {
		return nil, fmt.Errorf("parse: %w", err)
	}

	loadAnchors := func(anchors []Anchor, label string) error {
		for i := range anchors {
			ar, err := open(anchors[i].Path)
			if err != nil {
				return fmt.Errorf("%s anchor %d: open: %w", label, i, err)
			}
			anchors[i].Image, err = loadAnchorFromReader(ar, &tmpl.Config)
			ar.Close()
			if err != nil {
				return fmt.Errorf("%s anchor %d: %w", label, i, err)
			}
		}
		return nil
	}

	for pi := range tmpl.Pages {
		if err := loadAnchors(tmpl.Pages[pi].Anchors, fmt.Sprintf("page %d", pi)); err != nil {
			tmpl.Close()
			return nil, err
		}
	}

	return &tmpl, nil
}

func loadAnchorFromReader(r io.Reader, conf *Config) (*gocv.Mat, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	img, err := gocv.IMDecode(data, gocv.IMReadGrayScale)
	if err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}
	if img.Empty() {
		return nil, fmt.Errorf("decoded image is empty")
	}

	if err := Binarize(&img, &img, conf); err != nil {
		img.Close()
		return nil, fmt.Errorf("binarize: %w", err)
	}
	return &img, nil
}
