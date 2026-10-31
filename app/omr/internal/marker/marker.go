package marker

import (
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"io"
	"math"
	"sort"
	"strings"

	"gocv.io/x/gocv"
)

type Bubble struct {
	Label string `json:"label"`
	X     int    `json:"x"`
	Y     int    `json:"y"`
	// BaselineBias corrects for this option's own printed glyph having
	// inherently more or less ink than its question's other options, even
	// completely unmarked -- e.g. a wide letter like "M" reads meaningfully
	// higher raw fill than a thin one like "I" from its own print alone. It's
	// the option's canonical (blank, unwarped) template fill minus its
	// question's mean canonical fill, precomputed once from the template's
	// pristine reference image through the same Binarize+scoreMask sampling
	// real detection uses (see app/omr/tmp_tools/calibrate_bias), so it's a
	// relative correction, not an absolute ink-level assumption. It's
	// subtracted from the option's measured fill before any of detectAnswers'
	// row-level statistics (baseline, gap, confidence) see it, so a wide
	// glyph's natural excess ink doesn't compete against a genuine mark on a
	// naturally thinner letter elsewhere in the same row. 0 (the default for
	// any template that doesn't set it) leaves detection exactly as before.
	BaselineBias float64 `json:"baselineBias"`
}

type Question struct {
	ID           string   `json:"id"`
	Type         string   `json:"type"` // "single" (default) or "multi"
	BubbleWidth  int      `json:"bubbleWidth"`
	BubbleHeight int      `json:"bubbleHeight"`
	Options      []Bubble `json:"options"`
}

// Config holds marking-specific parameters. Nil fields fall back to defaults:
// fillThreshold: 0.25, bubbleInset: 0.75, flagThreshold: 0.5, searchRadius: 0,
// labelInset: 0.4.
type Config struct {
	FillThreshold *float64 `json:"fillThreshold"`
	// SelectionThreshold is the minimum gap between the top fill and the
	// next-best candidate required to actually select an option, used in
	// place of FillThreshold for that specific check only. FillThreshold
	// alone is dual-purpose: detectAnswers also passes it to the alignment
	// search (see alignOffset) as the bar for trusting its own found gap
	// before falling back to guard-sum recovery, and lowering it to
	// recover marginal genuine marks on a wide, many-option row (where a
	// clean gap is naturally smaller than on a short row -- see
	// BaselineBias) also weakens that unrelated alignment fallback,
	// which can misfire on an entirely different, genuinely blank
	// question. Setting SelectionThreshold keeps FillThreshold's alignment
	// role untouched while independently tuning the selection cutoff. Nil
	// (default) falls back to FillThreshold, i.e. previous behavior.
	SelectionThreshold *float64 `json:"selectionThreshold"`
	BubbleInset        *float64 `json:"bubbleInset"`
	// FlagThreshold is the minimum confidence below which an answer is flagged
	// for manual review. Set to 0.0 to disable confidence-based flagging.
	FlagThreshold *float64 `json:"flagThreshold"`
	// SearchRadius is a per-axis pixel search window applied around each
	// bubble's template position. The fill ratio returned is the maximum found
	// across all (2*r+1)² candidate centres. Use 3–5 to tolerate small
	// printer/scanner misalignment without changing the warp pipeline.
	SearchRadius *int `json:"searchRadius"`
	// SearchGroupSize, when positive and less than a question's option
	// count, splits SearchRadius's whole-row shared-offset search into
	// contiguous groups of at most this many options, each aligned
	// independently via GroupSearchRadius instead of one shared (dx, dy)
	// for the entire row. This targets misalignment that grows across a
	// wide row (e.g. residual shear left over from the page-level anchor
	// warp) which no single shared offset can represent regardless of how
	// wide SearchRadius is made. A question with fewer options than this is
	// completely unaffected and keeps using SearchRadius exactly as
	// before -- so e.g. a template's short answer-grid questions can be
	// left untouched while only its wide identification rows get grouped,
	// without any per-question configuration. 0 (default) disables
	// grouping entirely.
	SearchGroupSize *int `json:"searchGroupSize"`
	// GroupSearchRadius is the search radius used for each group when
	// SearchGroupSize splits a row into groups, in place of SearchRadius.
	// It typically needs to be wider than SearchRadius: grouping narrows
	// what a group's internal gap comparison has to tolerate, but it
	// doesn't reduce how far from a group's own template position the true
	// offset can be, since a group far from the row's anchor-side edge can
	// still see the same absolute drift the whole row would. Must stay
	// well under half the vertical spacing to the next row of bubbles, or
	// the search can lock onto the same letter one row up or down instead
	// of this row's own. Ignored unless SearchGroupSize is set.
	GroupSearchRadius *int `json:"groupSearchRadius"`
	// LabelInset cuts a hole out of the centre of the alignment search's
	// sampling mask, sized as a fraction of the bubble radius. This stops a
	// bubble's own printed option label from pulling the alignment search
	// toward itself. Only alignment uses this mask; the final fill
	// measurement still samples the full disk (bubbleInset), so detection
	// sensitivity is unaffected. Set to 0.0 to sample the full disk for
	// alignment too, for templates that don't print anything inside bubbles.
	LabelInset *float64 `json:"labelInset"`
}

// Page holds the questions for a single exam page.
type Page struct {
	Questions []Question `json:"questions"`
}

// Template is the mark template for a single- or multi-page exam.
// Multi-page templates populate Pages; single-page templates may use the
// top-level Questions field for backward compatibility.
type Template struct {
	Config    Config     `json:"config"`
	Questions []Question `json:"questions,omitempty"` // single-page backward compat
	Pages     []Page     `json:"pages,omitempty"`     // multi-page
}

// pages returns the per-page question lists. Single-page templates that use
// the top-level Questions field are treated as a one-page template.
func (t *Template) pages() []Page {
	if len(t.Pages) > 0 {
		return t.Pages
	}
	return []Page{{Questions: t.Questions}}
}

// LoadTemplate parses a marking template from r.
func LoadTemplate(r io.Reader) (*Template, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	var tmpl Template
	if err := json.Unmarshal(data, &tmpl); err != nil {
		return nil, fmt.Errorf("parse: %w", err)
	}
	return &tmpl, nil
}

// Box is the bounding box (in scan pixel coordinates) of a single bubble,
// at the offset actually used to detect it rather than its raw template
// position, since warping isn't pixel-perfect. There's one of these per
// option in a question, selected or not, so a caller can render every
// bubble at its real position rather than guessing where an unselected one
// sits from the question's aggregate bounds.
type Box struct {
	Label    string `json:"label"`
	Selected bool   `json:"selected"`
	X        int    `json:"x"`
	Y        int    `json:"y"`
	Width    int    `json:"width"`
	Height   int    `json:"height"`
}

// QuestionBounds is the bounding box (in scan pixel coordinates) enclosing
// every one of a question's bubbles, not just the ones that were selected.
// Unlike SelectedBoxes, it's available even for a blank question, which
// makes it useful as a generous hover/click hit-region for a whole question
// rather than something to draw a visible highlight from.
type QuestionBounds struct {
	X      int `json:"x"`
	Y      int `json:"y"`
	Width  int `json:"width"`
	Height int `json:"height"`
}

type Answer struct {
	QuestionID string   `json:"questionID"`
	Selected   []string `json:"selected"`
	Confidence float64  `json:"confidence"`
	Flag       bool     `json:"flag"`
	// PageIndex is which page (0-based, matching Template.Pages and the scan's
	// page images) this question's bubbles were found on. Bounds and Boxes
	// below are in that page's pixel coordinates, so they don't mean anything
	// without it.
	PageIndex int            `json:"pageIndex"`
	Bounds    QuestionBounds `json:"bounds"`
	// Boxes is one Box per option in the question, in template order.
	Boxes []Box `json:"boxes"`
}

type Result struct {
	Answers []Answer
}

// Evaluate scores every question across all pages of the template.
// imgs must contain one binary image per page (output of the preprocessing
// pipeline), in page order. For single-page templates a one-element slice is
// expected.
func Evaluate(imgs []*gocv.Mat, tmpl *Template) (*Result, error) {
	pages := tmpl.pages()
	if len(imgs) != len(pages) {
		return nil, fmt.Errorf("template has %d page(s), got %d image(s)", len(pages), len(imgs))
	}

	threshold := 0.25
	if tmpl.Config.FillThreshold != nil {
		threshold = *tmpl.Config.FillThreshold
	}
	selectionThreshold := threshold
	if tmpl.Config.SelectionThreshold != nil {
		selectionThreshold = *tmpl.Config.SelectionThreshold
	}
	inset := 0.75
	if tmpl.Config.BubbleInset != nil {
		inset = *tmpl.Config.BubbleInset
	}
	flagThreshold := 0.5
	if tmpl.Config.FlagThreshold != nil {
		flagThreshold = *tmpl.Config.FlagThreshold
	}
	searchRadius := 0
	if tmpl.Config.SearchRadius != nil {
		searchRadius = *tmpl.Config.SearchRadius
	}
	searchGroupSize := 0
	if tmpl.Config.SearchGroupSize != nil {
		searchGroupSize = *tmpl.Config.SearchGroupSize
	}
	groupSearchRadius := 0
	if tmpl.Config.GroupSearchRadius != nil {
		groupSearchRadius = *tmpl.Config.GroupSearchRadius
	}
	labelInset := 0.4
	if tmpl.Config.LabelInset != nil {
		labelInset = *tmpl.Config.LabelInset
	}

	var answers []Answer
	for i, img := range imgs {
		if img.Empty() {
			return nil, fmt.Errorf("page %d: cannot evaluate an empty image", i)
		}
		if len(pages[i].Questions) == 0 {
			return nil, fmt.Errorf("page %d: mark template contains no questions", i)
		}
		for _, q := range pages[i].Questions {
			selected, confidence, dxs, dys := detectAnswers(
				img, q, threshold, selectionThreshold, inset, labelInset, searchRadius, searchGroupSize, groupSearchRadius,
			)
			multiSelect := q.Type == "multi"
			flag := confidence < flagThreshold ||
				(len(selected) == 0 && strings.HasPrefix(q.ID, "Q")) ||
				(!multiSelect && len(selected) > 1)
			answers = append(answers, Answer{
				QuestionID: q.ID,
				Selected:   selected,
				Confidence: confidence,
				Flag:       flag,
				PageIndex:  i,
				Bounds:     questionBounds(q, dxs, dys),
				Boxes:      questionOptionBoxes(q, selected, dxs, dys),
			})
		}
	}

	return &Result{Answers: answers}, nil
}

// detectAnswers returns the selected option labels, the detection
// confidence, and the per-option (dx, dy) alignment offsets (relative to
// the template's bubble positions, one pair per q.Options entry in order)
// that were used to take the measurements.
func detectAnswers(
	img *gocv.Mat, q Question, threshold, selectionThreshold, inset, labelInset float64,
	searchRadius, searchGroupSize, groupSearchRadius int,
) ([]string, float64, []int, []int) {
	if len(q.Options) == 0 {
		return nil, 0.0, nil, nil
	}

	n := len(q.Options)
	w, h := q.BubbleWidth, q.BubbleHeight
	r := min(w, h) / 2

	innerR := int(float64(r) * inset)
	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}

	// scoreMask is the full disk out to innerR. It measures the actual fill
	// once alignment is settled, so a light or centre-concentrated mark
	// still counts in full.
	scoreMask := gocv.NewMatWithSize(h, w, gocv.MatTypeCV8U)
	defer scoreMask.Close()
	gocv.Circle(&scoreMask, image.Pt(w/2, h/2), innerR, white, -1)
	scoreArea := gocv.CountNonZero(scoreMask)
	scoreMasked := gocv.NewMat()
	defer scoreMasked.Close()

	// alignMask is the same disk with a hole punched out of the centre,
	// hiding the bubble's own printed letter from the alignment search.
	// Otherwise a heavily-inked letter can pull the search toward itself on
	// an unmarked bubble. This mask only picks (dx, dy); a real mark still
	// darkens the surrounding ring either way.
	labelR := int(float64(r) * labelInset)
	alignMask := gocv.NewMatWithSize(h, w, gocv.MatTypeCV8U)
	defer alignMask.Close()
	gocv.Circle(&alignMask, image.Pt(w/2, h/2), innerR, white, -1)
	if labelR > 0 {
		gocv.Circle(&alignMask, image.Pt(w/2, h/2), labelR, color.RGBA{}, -1)
	}
	alignArea := gocv.CountNonZero(alignMask)
	alignMasked := gocv.NewMat()
	defer alignMasked.Close()

	// guardMask is a disk drawn well past the bubble's own printed ring,
	// fixed regardless of the inset config. It's only used by the "is this
	// genuinely well-inked" check in the fallback below.
	//
	// scoreMask and alignMask are deliberately smaller than the ring, so a
	// real mark is measured precisely without surrounding print diluting it.
	// But that smallness is a trap for a fallback that just maximises raw
	// fill: on a blank bubble, drifting the sample toward the ring looks
	// like finding ink, with nothing to stop it short of the search radius.
	// guardMask already contains the whole ring at zero shift, so drifting
	// gets no false reward, and scoring itself stays untouched.
	const guardInset = 1.2
	guardInnerR := int(float64(r) * guardInset)
	guardMask := gocv.NewMatWithSize(h, w, gocv.MatTypeCV8U)
	defer guardMask.Close()
	gocv.Circle(&guardMask, image.Pt(w/2, h/2), guardInnerR, white, -1)
	guardArea := gocv.CountNonZero(guardMask)
	guardMasked := gocv.NewMat()
	defer guardMasked.Close()

	sample := func(cx, cy int, mask *gocv.Mat, area int, masked *gocv.Mat) (float64, bool) {
		if area == 0 {
			return 0.0, false
		}
		x0, y0 := cx-w/2, cy-h/2
		x1, y1 := x0+w, y0+h
		if x0 < 0 || y0 < 0 || x1 > img.Cols() || y1 > img.Rows() {
			return 0.0, false
		}
		roi := img.Region(image.Rect(x0, y0, x1, y1))
		defer roi.Close()
		gocv.BitwiseAnd(roi, *mask, masked)
		return float64(gocv.CountNonZero(*masked)) / float64(area), true
	}

	measure := func(cx, cy int) float64 {
		f, _ := sample(cx, cy, &scoreMask, scoreArea, &scoreMasked)
		return f
	}
	alignMeasure := func(cx, cy int) float64 {
		f, _ := sample(cx, cy, &alignMask, alignArea, &alignMasked)
		return f
	}
	guardMeasure := func(cx, cy int) float64 {
		f, _ := sample(cx, cy, &guardMask, guardArea, &guardMasked)
		return f
	}

	// Per-question alignment search: see alignOffset for the full
	// rationale. A wide row is split into contiguous groups when
	// searchGroupSize is set, each aligned independently via
	// groupSearchRadius; otherwise the whole row is aligned as one group via
	// searchRadius, exactly as before searchGroupSize existed.
	var dxs, dys []int
	if searchGroupSize > 0 && searchGroupSize < n {
		dxs = make([]int, n)
		dys = make([]int, n)
		for start := 0; start < n; start += searchGroupSize {
			end := min(start+searchGroupSize, n)
			gdx, gdy := alignOffset(q.Options[start:end], threshold, groupSearchRadius, alignMeasure, guardMeasure)
			for i := start; i < end; i++ {
				dxs[i], dys[i] = gdx, gdy
			}
		}
	} else {
		dx, dy := alignOffset(q.Options, threshold, searchRadius, alignMeasure, guardMeasure)
		dxs = make([]int, n)
		dys = make([]int, n)
		for i := range dxs {
			dxs[i], dys[i] = dx, dy
		}
	}

	// Measure raw fill ratios at the chosen offsets, then immediately
	// de-bias each one by its own option's BaselineBias (see Bubble). Doing
	// this here, before any row-level statistic below has seen a single
	// fill value, means everything downstream -- baseline, gap, confidence
	// -- already operates on de-biased fills without needing its own
	// awareness of per-letter ink variance.
	fills := make([]float64, n)
	for i, bubble := range q.Options {
		fills[i] = measure(bubble.X+dxs[i], bubble.Y+dys[i]) - bubble.BaselineBias
	}

	// Baseline is the row's background unmarked ink level. We subtract it
	// below so printed labels inside empty bubbles read close to zero.
	//
	// The simplest estimate, the row's literal minimum fill, is a bad one:
	// it always chases whichever glyph happens to be thinnest, so it gets
	// more extreme as the option count grows. A 26-letter name row always
	// includes the single thinnest glyph in the alphabet, while a 5-option
	// question only ever draws from 5 letters. That alone suppresses
	// confidence on wide rows, regardless of which letter is actually
	// marked.
	//
	// Instead we find the row's own largest gap in raw fill, the same
	// split the selection logic below finds independently, just computed
	// here on raw fills before baseline is subtracted (a uniform shift
	// can't move where the biggest gap falls). Everything at or below that
	// split is the row's unmarked cluster, and its mean is the baseline.
	// This correctly excludes however many bubbles are actually marked,
	// and uses every unmarked sample in the row instead of chasing a
	// single extreme one.
	sortedRaw := make([]float64, n)
	copy(sortedRaw, fills)
	sort.Float64s(sortedRaw)

	var maxGapRaw, splitAtRaw float64
	switch {
	case n < 2:
		// Nothing to compare against; no gap is possible either way.
		splitAtRaw = sortedRaw[n-1]
	case q.Type == "multi":
		// Multi-select: an unknown number of options may be genuinely
		// marked, so the real cluster boundary can fall anywhere in the
		// sorted list -- search for the single largest gap, as before.
		splitAtRaw = sortedRaw[n-1]
		for i := 1; i < n; i++ {
			if g := sortedRaw[i] - sortedRaw[i-1]; g > maxGapRaw {
				maxGapRaw = g
				splitAtRaw = sortedRaw[i-1]
			}
		}
	default:
		// Single-select: normally exactly one option is marked, but a
		// student can genuinely double- or triple-mark by mistake, which
		// should still come back as multiple selections (so Evaluate's
		// own single-select-with-multiple-selections check can flag it),
		// not get silently reduced to one -- so this can't rigidly pin the
		// split to top-1-vs-top-2 the way that would suggest. But it also
		// shouldn't search the *entire* sorted list the way multi-select
		// does: a spurious gap found low in a mostly-blank row (ink-
		// variation noise among options that were never marked at all --
		// see BaselineBias) doesn't just misfire quietly, everything above
		// that point reads as "selected", so a low-positioned false gap
		// can select most of a 26-option row at once. Limiting the search
		// to the top few ranks keeps genuine double/triple-marks
		// detectable while making that low-gap failure mode unreachable:
		// even in the worst case, only a handful of options can ever be
		// selected, never a large swath that was never marked.
		const maxPlausibleMarks = 4
		top := min(maxPlausibleMarks, n)
		splitAtRaw = sortedRaw[n-1]
		for i := n - top + 1; i < n; i++ {
			if g := sortedRaw[i] - sortedRaw[i-1]; g > maxGapRaw {
				maxGapRaw = g
				splitAtRaw = sortedRaw[i-1]
			}
		}
	}

	baselineSum, baselineCount := 0.0, 0
	for _, f := range fills {
		if f <= splitAtRaw {
			baselineSum += f
			baselineCount++
		}
	}
	baseline := baselineSum / float64(baselineCount)

	// allFilled is true when even the row's unmarked cluster looks
	// substantially filled: every bubble is probably marked, so we skip
	// normalization and fall back to absolute detection below.
	//
	// This looks similar to checking maxGapRaw < threshold (no clean
	// split), but it's not the same thing and isn't redundant with it. A
	// pure gap check can't tell a genuinely all-filled row apart from a
	// flat, low-ink row where the sample just landed off target. Replacing
	// this with a gap check alone broke exactly that case in testing.
	// There's a known, separate edge case this doesn't catch either: a
	// heavy print font can leave the unmarked cluster's mean under 0.75
	// while its top is still too close to a real mark for the gap check to
	// trust, and nothing gets selected at all. Fixing that needs its own
	// signal, not a reuse of this check or of threshold.
	const maxLetterBaseline = 0.75
	allFilled := baseline > maxLetterBaseline
	if allFilled {
		baseline = 0.0
	}

	adjusted := make([]float64, n)
	for i, f := range fills {
		adjusted[i] = f - baseline
	}

	// Gap-based selection: everything above the row's largest gap is
	// "selected". selectionThreshold is the minimum gap required for a
	// selection to count. Gaps smaller than this are just noise from ink
	// variation between letter shapes (a "W" carries roughly 4x the ink of
	// an "I" across a 26-option row) -- which is also why this can need to
	// be smaller than a short row's natural gap: with more options to draw
	// from, a genuine mark's gap over the best-competing unmarked option
	// is naturally tighter than on a row with only a handful of options.
	//
	// We don't need to re-sort and re-scan adjusted here. Subtracting a
	// constant from every value can't change any pairwise gap, so
	// maxGapRaw and splitAtRaw, shifted by baseline, already describe the
	// same split found above. That holds in the allFilled case too, since
	// baseline is forced to 0.0 there and adjusted becomes fills exactly.
	//
	// When allFilled is set there's no meaningful gap to trust, so
	// selection falls back to an absolute 0.5 cutoff instead.
	maxGap := maxGapRaw
	splitAt := splitAtRaw - baseline

	var answered []string
	var selectedFills []float64
	var highestFill float64
	var highestUnselected float64

	for i, bubble := range q.Options {
		adj := adjusted[i]
		if adj > highestFill {
			highestFill = adj
		}
		gapSelected := !allFilled && maxGap >= selectionThreshold && adj > splitAt
		absSelected := allFilled && adj >= 0.5
		if gapSelected || absSelected {
			answered = append(answered, bubble.Label)
			selectedFills = append(selectedFills, adj)
		} else if adj > highestUnselected {
			highestUnselected = adj
		}
	}

	var confidence float64
	if len(answered) == 0 {
		// How confidently blank: 1.0 when all adjusted fills are identical.
		confidence = 1.0 - highestFill
	} else {
		minSelected := selectedFills[0]
		for _, f := range selectedFills[1:] {
			if f < minSelected {
				minSelected = f
			}
		}
		if allFilled {
			// No unselected bubble is left to measure a margin against.
			// That limits what confidence can mean here, but it doesn't
			// mean the read itself is uncertain: every option reading as
			// filled is often the clearest possible observation about the
			// page. Evaluate already flags any single-select answer with
			// more than one selection, regardless of this value, so
			// forcing it to 0 here would only be misleading, not useful.
			// Report how strongly the weakest marked bubble is filled,
			// same as a multi-select row where "everything marked" can
			// genuinely be correct.
			confidence = minSelected
		} else {
			// How cleanly the marked bubbles separate from the unmarked
			// ones, relative to how much ink a real mark leaves. A plain
			// margin understates confidence for clean marks on questions
			// with more options, since letterform variation among
			// unmarked bubbles narrows the raw gap without the read being
			// any less certain. sortedRaw[n-1] minus baseline is the
			// largest adjusted fill overall, which always belongs to a
			// selected bubble.
			confidence = (minSelected - highestUnselected) / (sortedRaw[n-1] - baseline)
		}
	}

	confidence = math.Max(confidence, 0.0)
	confidence = math.Min(confidence, 1.0)

	return answered, confidence, dxs, dys
}

// alignOffset finds the (dx, dy) offset within ±radius that maximises the
// gap between opts' sorted fills -- the offset where a marked bubble stands
// out most clearly from the rest of opts. We use gap, not raw fill, because
// ring ink inflates every option about equally as the window drifts. Raw
// fill would reward that drift; gap mostly cancels it out.
//
// opts is a subset of a question's options when called per-group (see
// detectAnswers' searchGroupSize handling) or the whole question's options
// otherwise -- either way, alignment only ever compares within whatever
// opts it's given, never across a boundary the caller didn't include.
func alignOffset(
	opts []Bubble, threshold float64, radius int, alignMeasure, guardMeasure func(cx, cy int) float64,
) (int, int) {
	// offBubbleFloor exists because a real bubble always has some ink, from
	// its ring or its letter. A fill this low means the sample has drifted
	// off the bubble entirely. Without this floor, that near-zero reading
	// always wins the biggest gap, so the search would just walk to the
	// edge of the radius chasing it instead of a real mark.
	const offBubbleFloor = 0.05

	n := len(opts)
	bestDX, bestDY := 0, 0
	if radius <= 0 {
		return bestDX, bestDY
	}

	sortBuf := make([]float64, n)

	gapAt := func(dx, dy int) (float64, bool) {
		for i, b := range opts {
			f := alignMeasure(b.X+dx, b.Y+dy)
			if f < offBubbleFloor {
				return 0, false
			}
			sortBuf[i] = f
		}
		sort.Float64s(sortBuf)
		maxGap := 0.0
		for i := 1; i < n; i++ {
			if g := sortBuf[i] - sortBuf[i-1]; g > maxGap {
				maxGap = g
			}
		}
		return maxGap, true
	}

	// Start from the centred offset's own gap, not 0.0. Otherwise ties
	// always go to whichever candidate is checked first (the window's
	// top-left corner), dragging ambiguous questions toward that corner
	// instead of leaving them centred.
	//
	// The centred offset can itself fail the off-bubble floor. This is
	// common on a wide row: alignMask hides each bubble's printed
	// label, so a thin blank glyph's ring ink alone can dip below the
	// floor even when nothing's wrong. haveBest tracks whether we have
	// a real candidate yet. If centred fails, the loop below takes the
	// first valid candidate as its starting point instead of defaulting
	// to 0, which used to let any candidate with gap > 0 win by default.
	bestGapScore, haveBest := gapAt(0, 0)
	for dy := -radius; dy <= radius; dy++ {
		for dx := -radius; dx <= radius; dx++ {
			if dx == 0 && dy == 0 {
				continue
			}
			if gap, ok := gapAt(dx, dy); ok && (!haveBest || gap > bestGapScore) {
				bestGapScore = gap
				bestDX, bestDY = dx, dy
				haveBest = true
			}
		}
	}

	// A gap this small means fills are nearly uniform across all
	// options. Either everything's genuinely marked, or nothing is. Two
	// different checks below tell those apart.
	if bestGapScore < threshold {
		// Look for a position with real ink across the board. This is
		// what recovers a shifted all-filled row, which reads weak at
		// the template's own centre by definition (that's why it needed
		// a search at all). We use guardMeasure here, not measure or
		// alignMeasure: those are sized for precise scoring, which is
		// exactly what makes a fill-maximising search drift toward the
		// ring on a blank bubble instead of stopping at the true mark.
		centeredSum := 0.0
		for _, b := range opts {
			centeredSum += guardMeasure(b.X, b.Y)
		}
		sumDX, sumDY := 0, 0
		bestSum := centeredSum
		for dy := -radius; dy <= radius; dy++ {
			for dx := -radius; dx <= radius; dx++ {
				if dx == 0 && dy == 0 {
					continue
				}
				sum := 0.0
				for _, b := range opts {
					sum += guardMeasure(b.X+dx, b.Y+dy)
				}
				if sum > bestSum {
					bestSum = sum
					sumDX, sumDY = dx, dy
				}
			}
		}

		if bestSum/float64(n) > 0.5 {
			// Found a position with real ink across the board. Trust it.
			bestDX, bestDY = sumDX, sumDY
		} else {
			// Genuinely blank, or a single ordinary mark, not
			// all-filled. Nothing above confidently identifies a real
			// shift, so stay at the template's own position instead of
			// keeping whatever offset the primary gap search landed on.
			// That search only needed a gap above the floor to move off
			// centre, not one above threshold. On a wide mostly-blank
			// row, some noisy off-centre offset commonly clears the
			// floor without being the true alignment. This stops that
			// noise from silently relocating the sample window for the
			// fill measurement below.
			bestDX, bestDY = 0, 0
		}
	}

	return bestDX, bestDY
}

// questionOptionBoxes returns one Box per option in q, in template order,
// each shifted by the (dx, dy) alignment offset detectAnswers found for
// that specific option (dxs/dys, one entry per q.Options in order) and
// flagged with whether that option is in selected.
func questionOptionBoxes(q Question, selected []string, dxs, dys []int) []Box {
	selectedSet := make(map[string]bool, len(selected))
	for _, label := range selected {
		selectedSet[label] = true
	}
	boxes := make([]Box, len(q.Options))
	for i, opt := range q.Options {
		boxes[i] = Box{
			Label:    opt.Label,
			Selected: selectedSet[opt.Label],
			X:        opt.X + dxs[i] - q.BubbleWidth/2,
			Y:        opt.Y + dys[i] - q.BubbleHeight/2,
			Width:    q.BubbleWidth,
			Height:   q.BubbleHeight,
		}
	}
	return boxes
}

// questionBounds returns the bounding box (in scan pixel coordinates)
// enclosing all of a question's bubbles, each shifted by its own (dx, dy)
// alignment offset from detectAnswers (dxs/dys, one entry per q.Options in
// order). Mirrors the bounds computation the snippet handler uses for
// cropping (internal/httpserver/handler/snippet.go), but at the detected
// offsets rather than the raw template positions.
func questionBounds(q Question, dxs, dys []int) QuestionBounds {
	minX, minY := math.MaxInt, math.MaxInt
	maxX, maxY := math.MinInt, math.MinInt
	for i, opt := range q.Options {
		minX = min(minX, opt.X+dxs[i]-q.BubbleWidth/2)
		minY = min(minY, opt.Y+dys[i]-q.BubbleHeight/2)
		maxX = max(maxX, opt.X+dxs[i]+q.BubbleWidth/2)
		maxY = max(maxY, opt.Y+dys[i]+q.BubbleHeight/2)
	}
	return QuestionBounds{X: minX, Y: minY, Width: maxX - minX, Height: maxY - minY}
}
