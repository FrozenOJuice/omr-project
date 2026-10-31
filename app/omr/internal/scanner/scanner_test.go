package scanner

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gocv.io/x/gocv"
)

var black = gocv.NewScalar(0, 0, 0, 255)
var white = gocv.NewScalar(255, 255, 255, 255)

func assertError(t *testing.T, err error, expectError bool, errContains string) {
	t.Helper()

	if expectError {
		if err == nil {
			t.Fatalf("expected an error containing %q, but got nil", errContains)
		}
		if !strings.Contains(err.Error(), errContains) {
			t.Errorf("expected error to contain %q, but got %q", errContains, err.Error())
		}
		return
	}

	if err != nil {
		t.Fatalf("did not expect an error, but got: %v", err)
	}
}

func loadTestTemplate(t *testing.T) *Template {
	t.Helper()

	f, err := os.Open("testdata/template.json")
	if err != nil {
		t.Fatalf("open template: %v", err)
	}
	defer f.Close()

	tmpl, err := LoadTemplate(f, func(path string) (io.ReadCloser, error) {
		return os.Open(filepath.Join("testdata", path))
	})
	if err != nil {
		t.Fatalf("load template: %v", err)
	}
	t.Cleanup(tmpl.Close)

	return tmpl
}

func TestScan(t *testing.T) {
	if _, err := os.Stat("testdata/input.jpg"); err != nil {
		t.Skip("testdata not present, skipping integration test")
	}

	tmpl := loadTestTemplate(t)

	imgFile, err := os.Open("testdata/input.jpg")
	if err != nil {
		t.Fatalf("open image: %v", err)
	}
	defer imgFile.Close()

	results, err := Scan([]io.Reader{imgFile}, tmpl)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	defer results[0].Close()

	if results[0].Picture.Cols() != tmpl.Width || results[0].Picture.Rows() != tmpl.Height {
		t.Errorf("expected output %dx%d, got %dx%d",
			tmpl.Width, tmpl.Height, results[0].Picture.Cols(), results[0].Picture.Rows())
	}
}

// TestScanUpsideDown feeds a page rotated 180° through Scan and expects it
// to succeed anyway: recoverUpsideDown should rotate the frame back and
// re-match before giving up.
func TestScanUpsideDown(t *testing.T) {
	if _, err := os.Stat("testdata/input.jpg"); err != nil {
		t.Skip("testdata not present, skipping integration test")
	}

	tmpl := loadTestTemplate(t)

	img := gocv.IMRead("testdata/input.jpg", gocv.IMReadGrayScale)
	if img.Empty() {
		t.Fatalf("read testdata/input.jpg")
	}
	defer img.Close()

	flipped := gocv.NewMat()
	defer flipped.Close()

	if err := gocv.Rotate(img, &flipped, gocv.Rotate180Clockwise); err != nil {
		t.Fatalf("rotate: %v", err)
	}

	buf, err := gocv.IMEncode(gocv.JPEGFileExt, flipped)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	defer buf.Close()

	results, err := Scan([]io.Reader{bytes.NewReader(buf.GetBytes())}, tmpl)
	if err != nil {
		t.Fatalf("Scan failed on upside-down page: %v", err)
	}
	defer results[0].Close()

	if results[0].Picture.Cols() != tmpl.Width || results[0].Picture.Rows() != tmpl.Height {
		t.Errorf("expected output %dx%d, got %dx%d",
			tmpl.Width, tmpl.Height, results[0].Picture.Cols(), results[0].Picture.Rows())
	}
}

func TestBinarize(t *testing.T) {
	empty := gocv.NewMat()

	valid := gocv.NewMatWithSizeFromScalar(white, 500, 500, gocv.MatTypeCV8UC3)
	defer valid.Close()

	validConf := Config{BlurSize: 5, MorphCloseSize: 3}

	tests := []struct {
		name        string
		src         gocv.Mat
		conf        Config
		expectError bool
		errContains string
	}{
		{
			name:        "Fails on empty",
			src:         empty,
			conf:        validConf,
			expectError: true,
			errContains: "empty image",
		},
		{
			name:        "Fails on even blur size",
			src:         valid,
			conf:        Config{BlurSize: 4, MorphCloseSize: 3},
			expectError: true,
			errContains: "blurSize must be odd",
		},
		{
			name:        "Succeeds",
			src:         valid,
			conf:        validConf,
			expectError: false,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dst := gocv.NewMat()
			defer dst.Close()

			err := Binarize(&tc.src, &dst, &tc.conf)
			assertError(t, err, tc.expectError, tc.errContains)

			if !tc.expectError && dst.Channels() != 1 {
				t.Errorf("expected 1 channel (binary), but got %d", dst.Channels())
			}
		})
	}
}

func TestScaleROI(t *testing.T) {
	tests := []struct {
		name   string
		roi    image.Rectangle
		src    image.Point
		target image.Point
		want   image.Rectangle
	}{
		{
			name:   "Identity when src equals target",
			roi:    image.Rect(100, 200, 300, 400),
			src:    image.Pt(1200, 1700),
			target: image.Pt(1200, 1700),
			want:   image.Rect(100, 200, 300, 400),
		},
		{
			name:   "Halves ROI when src is half of target",
			roi:    image.Rect(100, 200, 300, 400),
			src:    image.Pt(600, 850),
			target: image.Pt(1200, 1700),
			want:   image.Rect(50, 100, 150, 200),
		},
		{
			name:   "Doubles ROI when src is double target",
			roi:    image.Rect(100, 200, 300, 400),
			src:    image.Pt(2400, 3400),
			target: image.Pt(1200, 1700),
			want:   image.Rect(200, 400, 600, 800),
		},
		{
			name:   "Zero origin is preserved",
			roi:    image.Rect(0, 0, 600, 850),
			src:    image.Pt(600, 850),
			target: image.Pt(1200, 1700),
			want:   image.Rect(0, 0, 300, 425),
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := scaleROI(tc.roi, tc.src, tc.target)
			if got != tc.want {
				t.Errorf("scaleROI(%v, %v, %v) = %v, want %v",
					tc.roi, tc.src, tc.target, got, tc.want)
			}
		})
	}
}

func TestFindAnchorCenter(t *testing.T) {
	const (
		imgW, imgH   = 300, 300
		tmplW, tmplH = 60, 60
		patX, patY   = 100, 100
	)

	binary := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer binary.Close()
	gocv.Rectangle(&binary,
		image.Rect(patX+5, patY+5, patX+tmplW-5, patY+tmplH-5),
		color.RGBA{R: 255, G: 255, B: 255, A: 255}, -1)

	// The white rectangle is inset by 5px so the template has a black border,
	// giving TmCcoeffNormed a non-zero standard deviation to divide by.
	template := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), tmplH, tmplW, gocv.MatTypeCV8UC1)
	defer template.Close()
	gocv.Rectangle(&template,
		image.Rect(5, 5, tmplW-5, tmplH-5),
		color.RGBA{R: 255, G: 255, B: 255, A: 255}, -1)

	expectedCenter := image.Pt(patX+tmplW/2, patY+tmplH/2)

	tests := []struct {
		name          string
		roi           image.Rectangle
		minConfidence float32
		expectError   bool
		errContains   string
	}{
		{
			name:          "Finds pattern within full image ROI",
			roi:           image.Rect(0, 0, imgW, imgH),
			minConfidence: 0.5,
			expectError:   false,
		},
		{
			name:          "Finds pattern with offset ROI",
			roi:           image.Rect(50, 50, imgW, imgH),
			minConfidence: 0.5,
			expectError:   false,
		},
		{
			name:          "Fails when confidence threshold cannot be met",
			roi:           image.Rect(0, 0, imgW, imgH),
			minConfidence: 2.0,
			expectError:   true,
			errContains:   "below threshold",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			anchor := Anchor{
				Image: &template,
				ROI:   tc.roi,
			}

			pt, err := findAnchorCenter(binary, anchor, tc.minConfidence)
			assertError(t, err, tc.expectError, tc.errContains)

			if !tc.expectError && pt != expectedCenter {
				t.Errorf("expected center %v, got %v", expectedCenter, pt)
			}
		})
	}
}

// marker returns a small template: a white square inset by 5px on a black
// background, the same shape TestFindAnchorCenter uses, so it has a
// non-zero standard deviation for TmCcoeffNormed to divide by.
func marker(size int) gocv.Mat {
	m := gocv.NewMatWithSizeFromScalar(gocv.NewScalar(0, 0, 0, 0), size, size, gocv.MatTypeCV8UC1)
	gocv.Rectangle(&m,
		image.Rect(5, 5, size-5, size-5),
		color.RGBA{R: 255, G: 255, B: 255, A: 255}, -1)
	return m
}

// bullseyeMarker draws a black outer disk -> white ring -> black centre dot,
// the same anchor pattern exam_generator.py's _draw_anchor_image produces
// for real exam templates. Unlike marker's plain inset square, this keeps
// enough contrast after Binarize's blur/adaptive-threshold/morph-close to
// still match reliably, so it's used by tests that (unlike
// TestDetectMisplacedPage) exercise the full Binarize+warp pipeline.
func bullseyeMarker(size int) gocv.Mat {
	m := gocv.NewMatWithSizeFromScalar(gocv.NewScalar(255, 255, 255, 255), size, size, gocv.MatTypeCV8UC1)
	center := image.Pt(size/2, size/2)
	r := size / 2
	black := color.RGBA{A: 255}
	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}
	gocv.Circle(&m, center, r, black, -1)
	gocv.Circle(&m, center, r*3/4, white, -1)
	gocv.Circle(&m, center, r/3, black, -1)
	return m
}

// stampMarkers draws a copy of mark centered at each point in centers onto
// canvas.
func stampMarkers(canvas gocv.Mat, mark gocv.Mat, centers []image.Point) {
	size := mark.Cols()
	for _, c := range centers {
		roi := canvas.Region(image.Rect(
			c.X-size/2, c.Y-size/2, c.X-size/2+size, c.Y-size/2+size,
		))
		mark.CopyTo(&roi)
		roi.Close()
	}
}

// anchorsAt builds a 3-anchor page (warp's minimum) using mark at the given
// centers, each searched only within a box around its own expected center —
// like real templates (e.g. ubc/scan.json), so a marker present at the
// wrong position isn't found by a search rooted at the right one.
func anchorsAt(mark gocv.Mat, centers []image.Point, searchMargin int) []Anchor {
	anchors := make([]Anchor, len(centers))
	for i, c := range centers {
		anchors[i] = Anchor{
			Image: &mark,
			ROI: image.Rect(
				c.X-searchMargin, c.Y-searchMargin,
				c.X+searchMargin, c.Y+searchMargin,
			),
			Center: c,
		}
	}
	return anchors
}

func TestDetectMisplacedPage(t *testing.T) {
	const canvasSize = 300
	const markSize = 40

	mark := marker(markSize)
	defer mark.Close()

	// Page A's layout: markers at top-left, top-right, bottom-left.
	// Page B's layout: markers at top-left, top-right, bottom-right — it
	// shares two of page A's three anchors, so a naive single-anchor check
	// wouldn't tell them apart, but the third (bottom-left vs bottom-right)
	// does.
	pageACenters := []image.Point{{X: 60, Y: 60}, {X: 240, Y: 60}, {X: 60, Y: 240}}
	pageBCenters := []image.Point{{X: 60, Y: 60}, {X: 240, Y: 60}, {X: 240, Y: 240}}

	tmpl := &Template{
		Width:  canvasSize,
		Height: canvasSize,
		Config: Config{BlurSize: 5, MorphCloseSize: 3, MinAnchorConfidence: 0.6},
		Pages: []ScanPage{
			{Anchors: anchorsAt(mark, pageACenters, 50)},
			{Anchors: anchorsAt(mark, pageBCenters, 50)},
		},
	}

	// canvasB is a page B scan (e.g. the back page) mistakenly fed in as if
	// it were page A (e.g. the front page's slot, idx 0).
	canvasB := gocv.NewMatWithSizeFromScalar(gocv.NewScalar(0, 0, 0, 0), canvasSize, canvasSize, gocv.MatTypeCV8UC1)
	defer canvasB.Close()
	stampMarkers(canvasB, mark, pageBCenters)

	colorMat := gocv.NewMat()
	defer colorMat.Close()
	gocv.CvtColor(canvasB, &colorMat, gocv.ColorGrayToBGR)

	data := &ScanData{Picture: colorMat, Binary: canvasB}

	// Sanity check: canvas B must actually fail to match page A's own
	// anchors (its bottom-left anchor has nothing there), otherwise this
	// test wouldn't be exercising the real failure -> detection path.
	probe := &ScanData{Picture: gocv.NewMat(), Binary: gocv.NewMat()}
	defer probe.Close()
	if err := warp(data, probe, tmpl.Pages[0].Anchors, canvasSize, canvasSize, tmpl.Config); err == nil {
		t.Fatalf("expected canvas B not to match page A's anchors")
	}

	detected, ok := detectMisplacedPage(data, tmpl, 0)
	if !ok {
		t.Fatalf("expected canvas B to be detected as a misplaced page")
	}
	if detected != 1 {
		t.Errorf("expected detected page 1, got %d", detected)
	}
}

// TestScanMultipleDpi exercises preprocessPage's ratio-based scaling
// (scaleConfig, and scaleAnchorTemplate's direction-aware interpolation)
// across scans captured well below, at, and above a template's calibration
// point, asserting warp still succeeds at each instead of only at the one
// DPI a template happens to be tuned for.
func TestScanMultipleDpi(t *testing.T) {
	const (
		nativeW, nativeH = 1200, 1700
		markSize         = 40
		// referenceRatio mirrors production, where exam templates are
		// uploaded via /scan/pdf at roughly 1.4x their own canvas size (the
		// historically known-good ~216 DPI operating point).
		referenceRatio = 1.4
		referenceDpi   = 216.0
	)

	conf := Config{
		BlurSize:            5,
		MorphCloseSize:      3,
		MinAnchorConfidence: 0.5,
		ReferenceRatio:      referenceRatio,
	}

	// The stored anchor image must be binarized the same way a real
	// template's anchor crop is at load time (see loadAnchorFromReader):
	// it's matched against an already-binarized scan, so matching a raw
	// grayscale template against that loses most of its confidence.
	mark := bullseyeMarker(markSize)
	defer mark.Close()
	if err := Binarize(&mark, &mark, &conf); err != nil {
		t.Fatalf("binarize anchor: %v", err)
	}

	centers := []image.Point{
		{X: 150, Y: 150},
		{X: nativeW - 150, Y: 150},
		{X: 150, Y: nativeH - 150},
	}

	tmpl := &Template{
		Width:  nativeW,
		Height: nativeH,
		Config: conf,
		Pages:  []ScanPage{{Anchors: anchorsAt(mark, centers, 80)}},
	}

	for _, dpi := range []float64{150, 216, 300} {
		t.Run(fmt.Sprintf("%.0fdpi", dpi), func(t *testing.T) {
			// scale is how big a scan at dpi is relative to the template's
			// own canvas size, following the same physical relationship
			// production scans have (see referenceRatio above).
			scale := referenceRatio * dpi / referenceDpi

			w := int(float64(nativeW)*scale + 0.5)
			h := int(float64(nativeH)*scale + 0.5)
			// Not deferred: on success, ownership passes into the returned
			// ScanData (same pattern as scanPage's img), which is what gets
			// closed below. Closing both would double-free the same Mat.
			canvas := gocv.NewMatWithSizeFromScalar(
				gocv.NewScalar(0, 0, 0, 0), h, w, gocv.MatTypeCV8UC1)

			scaledMark := bullseyeMarker(int(float64(markSize)*scale + 0.5))
			defer scaledMark.Close()

			scaledCenters := make([]image.Point, len(centers))
			for i, c := range centers {
				scaledCenters[i] = image.Pt(
					int(float64(c.X)*scale+0.5),
					int(float64(c.Y)*scale+0.5),
				)
			}
			stampMarkers(canvas, scaledMark, scaledCenters)

			data, err := preprocessPage(canvas, tmpl, 0)
			if err != nil {
				t.Fatalf(
					"preprocessPage failed at %.0f DPI (scale %.3f): %v",
					dpi, scale, err,
				)
			}
			defer data.Close()

			if data.Picture.Cols() != nativeW || data.Picture.Rows() != nativeH {
				t.Errorf(
					"expected warped output %dx%d, got %dx%d",
					nativeW, nativeH, data.Picture.Cols(), data.Picture.Rows(),
				)
			}
		})
	}
}

//
// Benchmarks
//

func BenchmarkScan(b *testing.B) {

	f, err := os.Open("testdata/template.json")
	if err != nil {
		b.Fatalf("open template: %v", err)
	}
	defer f.Close()

	tmpl, err := LoadTemplate(f, func(path string) (io.ReadCloser, error) {
		return os.Open(filepath.Join("testdata", path))
	})
	if err != nil {
		b.Fatalf("load template: %v", err)
	}
	defer tmpl.Close()

	imgFile, err := os.Open("testdata/input.jpg")
	if err != nil {
		b.Fatalf("open image: %v", err)
	}
	defer imgFile.Close()

	buf, err := io.ReadAll(imgFile)
	if err != nil {
		b.Fatal(err)
	}

	for b.Loop() {
		results, err := scanPage(buf, tmpl, 0)
		if err != nil {
			b.Fatal(err)
		}
		results.Close()
	}
}
