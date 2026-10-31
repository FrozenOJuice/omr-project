package marker

import (
	"embed"
	"image"
	"image/color"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"gocv.io/x/gocv"
)

//
// Helper functions
//

func ptr(f float64) *float64 { return &f }
func intPtr(i int) *int      { return &i }

func assertError(t *testing.T, err error, expectError bool, errContains string) {
	t.Helper()
	if expectError {
		if err == nil {
			t.Fatalf("expected an error containing %q, but got nil", errContains)
		}
		if !strings.Contains(err.Error(), errContains) {
			t.Errorf("expected error to contain %q, but got %q",
				errContains, err.Error())
		}
		return
	}
	if err != nil {
		t.Fatalf("did not expect an error, but got: %v", err)
	}
}

// fillBubble paints a white filled circle into img at the inset region of the
// bubble centered at (cx, cy) with dimensions (bw, bh). The circle radius
// matches what bubbleFillRatio samples, so a filled bubble reads back as ~1.0.
func fillBubble(img *gocv.Mat, cx, cy, bw, bh int, inset float64) {
	r := bw / 2
	if bh < bw {
		r = bh / 2
	}
	gocv.Circle(img,
		image.Pt(cx, cy),
		int(float64(r)*inset),
		color.RGBA{R: 255, G: 255, B: 255, A: 255},
		-1,
	)
}

func stringSlicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

//
// Tests
//

// TestMarkIntegration evaluates a real preprocessed exam scan against the
// mark template. Test data must be present in the testdata/ directory:
//
//	testdata/preprocessed.png  — binary image produced by `omr preprocess`
//	testdata/mark.json         — mark template
func TestMarkIntegration(t *testing.T) {
	const testdataDir = "testdata"

	preprocessedPath := filepath.Join(testdataDir, "preprocessed.png")
	if _, err := os.Stat(preprocessedPath); err != nil {
		t.Skip("testdata not present, skipping integration test")
	}

	img := gocv.IMRead(preprocessedPath, gocv.IMReadGrayScale)
	defer img.Close()
	if img.Empty() {
		t.Fatal("could not read preprocessed image")
	}

	markTmplFile, err := os.Open(filepath.Join(testdataDir, "mark.json"))
	if err != nil {
		t.Fatalf("open mark template: %v", err)
	}
	defer markTmplFile.Close()

	markTmpl, err := LoadTemplate(markTmplFile)
	if err != nil {
		t.Fatalf("load mark template: %v", err)
	}

	result, err := Evaluate([]*gocv.Mat{&img}, markTmpl)
	if err != nil {
		t.Fatalf("evaluate: %v", err)
	}

	if len(result.Answers) != 8 {
		t.Fatalf("expected 8 answers, got %d", len(result.Answers))
	}

	// Index answers by question ID for lookup below.
	byID := make(map[string]Answer, len(result.Answers))
	for _, ans := range result.Answers {
		byID[ans.QuestionID] = ans
	}

	// Verify the sheet is not read as entirely blank.
	answered := 0
	for _, ans := range result.Answers {
		if len(ans.Selected) > 0 {
			answered++
		}
	}
	if answered == 0 {
		t.Error("all questions read as blank — mark template may be misaligned")
	}

	// Spot-check known answers from the test sheet.
	checks := []struct {
		question string
		selected []string
		flagged  bool
	}{
		// Q2 was specified in the JSON as multi-select, so it won't get flagged
		{question: "Q1", selected: []string{"B"}, flagged: false},
		{question: "Q2", selected: []string{"C", "E"}, flagged: false},
		{question: "Q3", selected: []string{"B"}, flagged: false},
		{question: "Q4", selected: []string{"C"}, flagged: false},
		{question: "Q5", selected: []string{"B", "D"}, flagged: true},
		{question: "Q6", selected: []string{}, flagged: true},
		{question: "Q7", selected: []string{}, flagged: true},
		{question: "Q8", selected: []string{"B"}, flagged: false},
	}

	for _, c := range checks {
		ans, ok := byID[c.question]
		if !ok {
			t.Errorf("%s: not found in results", c.question)
			continue
		}
		if !stringSlicesEqual(ans.Selected, c.selected) {
			t.Errorf("%s: selected = %v, want %v",
				c.question, ans.Selected, c.selected)
		}
		if ans.Flag != c.flagged {
			t.Errorf("%s: flag = %v, want %v",
				c.question, ans.Flag, c.flagged)
		}
	}
}

func TestLoadTemplate(t *testing.T) {
	validJSON := `{
		"config": {},
		"questions": [{
			"id": "Q1",
			"bubbleWidth": 30,
			"bubbleHeight": 30,
			"options": [{"label": "A", "x": 0, "y": 0}]
		}]
	}`

	tests := []struct {
		name        string
		json        string
		expectError bool
		errContains string
	}{
		{name: "Valid template", json: validJSON},
		{name: "Invalid JSON", json: `{bad`, expectError: true, errContains: "parse"},
		{name: "Empty input", json: ``, expectError: true, errContains: "parse"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			tmpl, err := LoadTemplate(strings.NewReader(tc.json))
			assertError(t, err, tc.expectError, tc.errContains)
			if !tc.expectError && tmpl == nil {
				t.Error("expected non-nil template")
			}
		})
	}
}

func TestEvaluate(t *testing.T) {
	const (
		imgW, imgH = 400, 400
		bw, bh     = 30, 30
		inset      = 0.75
	)

	singleQ := Question{
		ID: "Q1", Type: "single",
		BubbleWidth: bw, BubbleHeight: bh,
		Options: []Bubble{
			{Label: "A", X: 65, Y: 115},
			{Label: "B", X: 115, Y: 115},
			{Label: "C", X: 165, Y: 115},
		},
	}
	multiQ := Question{
		ID: "Q1", Type: "multi",
		BubbleWidth: bw, BubbleHeight: bh,
		Options: []Bubble{
			{Label: "A", X: 65, Y: 115},
			{Label: "B", X: 115, Y: 115},
		},
	}

	defaultConfig := Config{
		FillThreshold: ptr(0.5),
		BubbleInset:   ptr(inset),
		FlagThreshold: ptr(0.5),
	}

	// Image with only bubble A of singleQ filled.
	imgOneSelected := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer imgOneSelected.Close()
	fillBubble(&imgOneSelected, 65, 115, bw, bh, inset)

	// Image with bubbles A and B of singleQ both filled.
	imgTwoSelected := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer imgTwoSelected.Close()
	fillBubble(&imgTwoSelected, 65, 115, bw, bh, inset)
	fillBubble(&imgTwoSelected, 115, 115, bw, bh, inset)

	// All-black image: no bubbles filled.
	imgBlank := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer imgBlank.Close()

	// Image with all three bubbles of singleQ filled, but the marks are
	// printed/scanned 8px off from their template positions — simulating
	// scan misalignment. Because every option is shifted identically, the
	// gap between sorted fills is exactly 0 at every search offset, so the
	// gap-maximising search alone has no signal to align on (regression:
	// previously this caused the question to read back as confidently
	// blank instead of all-filled). SearchRadius must be wide enough to
	// reach the true offset for the sum-fill fallback to recover it.
	const allFilledShiftX = 8
	imgAllSelectedShifted := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer imgAllSelectedShifted.Close()
	fillBubble(&imgAllSelectedShifted, 65+allFilledShiftX, 115, bw, bh, inset)
	fillBubble(&imgAllSelectedShifted, 115+allFilledShiftX, 115, bw, bh, inset)
	fillBubble(&imgAllSelectedShifted, 165+allFilledShiftX, 115, bw, bh, inset)

	// Same shift, but filled out to the bubble's full radius rather than
	// just `inset` of it -- needed for the search-radius recovery case
	// below, since the sum-fill fallback's guard mask deliberately samples
	// past that radius (see guardMask in marker.go) to stay exploit-proof,
	// so an ink circle calibrated to `inset` alone isn't dark enough for it
	// to register as "well-inked".
	imgAllSelectedShiftedFull := gocv.NewMatWithSizeFromScalar(
		gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	defer imgAllSelectedShiftedFull.Close()
	fillBubble(&imgAllSelectedShiftedFull, 65+allFilledShiftX, 115, bw, bh, 1.0)
	fillBubble(&imgAllSelectedShiftedFull, 115+allFilledShiftX, 115, bw, bh, 1.0)
	fillBubble(&imgAllSelectedShiftedFull, 165+allFilledShiftX, 115, bw, bh, 1.0)

	emptyImg := gocv.NewMat()
	defer emptyImg.Close()

	tests := []struct {
		name         string
		img          gocv.Mat
		tmpl         *Template
		expectError  bool
		errContains  string
		wantSelected [][]string
		wantFlagged  []bool
		// wantBoxes, when non-nil, checks answer[0]'s Boxes.
		wantBoxes []Box
		// wantBounds, when non-nil, checks answer[0]'s Bounds.
		wantBounds *QuestionBounds
	}{
		{
			name:        "Empty image returns error",
			img:         emptyImg,
			tmpl:        &Template{Config: defaultConfig, Questions: []Question{singleQ}},
			expectError: true,
			errContains: "empty image",
		},
		{
			name:        "Template with no questions returns error",
			img:         imgOneSelected,
			tmpl:        &Template{Config: defaultConfig, Questions: []Question{}},
			expectError: true,
			errContains: "no questions",
		},
		{
			name:         "Single-select: one bubble filled is not flagged",
			img:          imgOneSelected,
			tmpl:         &Template{Config: defaultConfig, Questions: []Question{singleQ}},
			wantSelected: [][]string{{"A"}},
			wantFlagged:  []bool{false},
			// Boxes cover every option, not just the selected one -- and sit
			// at each bubble's raw template position since no search radius
			// is configured.
			wantBoxes: []Box{
				{Label: "A", Selected: true, X: 50, Y: 100, Width: 30, Height: 30},
				{Label: "B", Selected: false, X: 100, Y: 100, Width: 30, Height: 30},
				{Label: "C", Selected: false, X: 150, Y: 100, Width: 30, Height: 30},
			},
			// Bounds spans all three options (A-C: X 65-165), same extent as
			// the union of Boxes above but without the per-bubble detail.
			wantBounds: &QuestionBounds{X: 50, Y: 100, Width: 130, Height: 30},
		},
		{
			name:         "Single-select: no bubble filled is flagged",
			img:          imgBlank,
			tmpl:         &Template{Config: defaultConfig, Questions: []Question{singleQ}},
			wantSelected: [][]string{nil},
			wantFlagged:  []bool{true},
		},
		{
			name:         "Single-select: two bubbles filled is flagged",
			img:          imgTwoSelected,
			tmpl:         &Template{Config: defaultConfig, Questions: []Question{singleQ}},
			wantSelected: [][]string{{"A", "B"}},
			wantFlagged:  []bool{true},
		},
		{
			name:         "Multi-select: two bubbles filled is not flagged",
			img:          imgTwoSelected,
			tmpl:         &Template{Config: defaultConfig, Questions: []Question{multiQ}},
			wantSelected: [][]string{{"A", "B"}},
			wantFlagged:  []bool{false},
		},
		{
			name:         "All options filled but shifted: without search radius reads as blank",
			img:          imgAllSelectedShifted,
			tmpl:         &Template{Config: defaultConfig, Questions: []Question{singleQ}},
			wantSelected: [][]string{nil},
			wantFlagged:  []bool{true},
		},
		{
			name: "All options filled but shifted: search radius recovers all-filled detection",
			img:  imgAllSelectedShiftedFull,
			tmpl: &Template{
				Config: Config{
					FillThreshold: ptr(0.5),
					BubbleInset:   ptr(inset),
					FlagThreshold: ptr(0.5),
					SearchRadius:  intPtr(allFilledShiftX),
				},
				Questions: []Question{singleQ},
			},
			wantSelected: [][]string{{"A", "B", "C"}},
			wantFlagged:  []bool{true},
			// Boxes must follow the detected alignment offset (+8 in X), not
			// the raw template position. That's the whole point of storing
			// the found location instead of relying on the static template.
			wantBoxes: []Box{
				{Label: "A", Selected: true, X: 65 + allFilledShiftX - 15, Y: 100, Width: 30, Height: 30},
				{Label: "B", Selected: true, X: 115 + allFilledShiftX - 15, Y: 100, Width: 30, Height: 30},
				{Label: "C", Selected: true, X: 165 + allFilledShiftX - 15, Y: 100, Width: 30, Height: 30},
			},
			wantBounds: &QuestionBounds{X: 50 + allFilledShiftX, Y: 100, Width: 130, Height: 30},
		},
		{
			name: "FlagThreshold above max confidence flags clear answers",
			img:  imgOneSelected,
			tmpl: &Template{
				Config: Config{
					FillThreshold: ptr(0.5),
					BubbleInset:   ptr(inset),
					FlagThreshold: ptr(1.1),
				},
				Questions: []Question{singleQ},
			},
			wantSelected: [][]string{{"A"}},
			wantFlagged:  []bool{true},
		},
		{
			name: "FlagThreshold zero disables confidence-based flagging",
			img:  imgOneSelected,
			tmpl: &Template{
				Config: Config{
					FillThreshold: ptr(0.5),
					BubbleInset:   ptr(inset),
					FlagThreshold: ptr(0.0),
				},
				Questions: []Question{singleQ},
			},
			wantSelected: [][]string{{"A"}},
			wantFlagged:  []bool{false},
		},
		{
			name:         "Nil config fields fall back to defaults",
			img:          imgOneSelected,
			tmpl:         &Template{Config: Config{}, Questions: []Question{singleQ}},
			wantSelected: [][]string{{"A"}},
			wantFlagged:  []bool{false},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			result, err := Evaluate([]*gocv.Mat{&tc.img}, tc.tmpl)
			assertError(t, err, tc.expectError, tc.errContains)
			if tc.expectError {
				return
			}

			if len(result.Answers) != len(tc.wantSelected) {
				t.Fatalf("expected %d answers, got %d",
					len(tc.wantSelected), len(result.Answers))
			}
			for i, ans := range result.Answers {
				if !stringSlicesEqual(ans.Selected, tc.wantSelected[i]) {
					t.Errorf("answer[%d]: selected = %v, want %v",
						i, ans.Selected, tc.wantSelected[i])
				}
				if ans.Flag != tc.wantFlagged[i] {
					t.Errorf("answer[%d]: flag = %v, want %v",
						i, ans.Flag, tc.wantFlagged[i])
				}
				if tc.wantBoxes != nil && i == 0 {
					if !reflect.DeepEqual(ans.Boxes, tc.wantBoxes) {
						t.Errorf("answer[0]: boxes = %+v, want %+v", ans.Boxes, tc.wantBoxes)
					}
				}
				if tc.wantBounds != nil && i == 0 {
					if ans.Bounds != *tc.wantBounds {
						t.Errorf("answer[0]: bounds = %+v, want %+v", ans.Bounds, *tc.wantBounds)
					}
				}
				// None of the cases above use a multi-page template, so every
				// answer should be attributed to page 0.
				if ans.PageIndex != 0 {
					t.Errorf("answer[%d]: pageIndex = %d, want 0", i, ans.PageIndex)
				}
			}
		})
	}
}

// TestEvaluate_PageIndex checks that answers are attributed to the page they
// were actually found on, not just page 0. Annotation rendering depends on
// this, since each page has its own pixel coordinate space.
func TestEvaluate_PageIndex(t *testing.T) {
	const imgW, imgH, bw, bh = 400, 400, 30, 30

	q := func(id string) Question {
		return Question{
			ID: id, Type: "single",
			BubbleWidth: bw, BubbleHeight: bh,
			Options: []Bubble{
				{Label: "A", X: 65, Y: 115},
				{Label: "B", X: 115, Y: 115},
			},
		}
	}

	newImg := func() gocv.Mat {
		return gocv.NewMatWithSizeFromScalar(
			gocv.NewScalar(0, 0, 0, 0), imgH, imgW, gocv.MatTypeCV8UC1)
	}
	page0Img := newImg()
	defer page0Img.Close()
	fillBubble(&page0Img, 65, 115, bw, bh, 0.75)
	page1Img := newImg()
	defer page1Img.Close()
	fillBubble(&page1Img, 115, 115, bw, bh, 0.75)

	tmpl := &Template{
		Config: Config{FillThreshold: ptr(0.5), BubbleInset: ptr(0.75), FlagThreshold: ptr(0.5)},
		Pages: []Page{
			{Questions: []Question{q("Q1")}},
			{Questions: []Question{q("Q2")}},
		},
	}

	result, err := Evaluate([]*gocv.Mat{&page0Img, &page1Img}, tmpl)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Answers) != 2 {
		t.Fatalf("expected 2 answers, got %d", len(result.Answers))
	}
	if result.Answers[0].PageIndex != 0 {
		t.Errorf("Q1: pageIndex = %d, want 0", result.Answers[0].PageIndex)
	}
	if result.Answers[1].PageIndex != 1 {
		t.Errorf("Q2: pageIndex = %d, want 1", result.Answers[1].PageIndex)
	}
}

//
// Benchmarks
//

//go:embed testdata/*
var testData embed.FS

func BenchmarkEvaluate(b *testing.B) {

	buf, err := testData.ReadFile("testdata/preprocessed.png")
	if err != nil {
		b.Fatal("failed to read testdata/preprocessed.png")
	}

	img, err := gocv.IMDecode(buf, gocv.IMReadGrayScale)
	if err != nil || img.Empty() {
		b.Fatal("could not read preprocessed image")
	}
	defer img.Close()

	r, err := testData.Open("testdata/mark.json")
	if err != nil {
		b.Fatalf("open mark template: %v", err)
	}
	defer r.Close()

	tmpl, err := LoadTemplate(r)
	if err != nil {
		b.Fatalf("load mark template: %v", err)
	}

	for b.Loop() {
		_, err = Evaluate([]*gocv.Mat{&img}, tmpl)
		if err != nil {
			b.Fatalf("evaluate: %v", err)
		}
	}
}
