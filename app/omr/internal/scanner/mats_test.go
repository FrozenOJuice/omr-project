package scanner

import (
	"embed"
	"fmt"
	"io"
	"testing"

	"gocv.io/x/gocv"
)

//
// Helper functions
//

//go:embed testdata/*
var testData embed.FS

func loadExamBatch(t *testing.T) ([]*gocv.Mat, *Template) {
	t.Helper()

	const (
		nExams        = 2
		nPagesPerExam = 2
	)

	mats := make([]*gocv.Mat, nExams*nPagesPerExam)
	for i := range nExams {
		for j := range nPagesPerExam {

			img, err := testData.ReadFile(
				fmt.Sprintf("testdata/multipage/exam%dpage%d.%s", i, j, []string{"jpeg", "png"}[j]),
			)
			if err != nil {
				t.Fatal(err)
			}

			mat, err := gocv.IMDecode(img, gocv.IMReadGrayScale)
			if err != nil {
				t.Fatal(err)
			}

			mats[i*nPagesPerExam+j] = &mat

		}
	}

	f, err := testData.Open("testdata/multipage/preprocessing_template.json")
	if err != nil {
		t.Fatal(err)
	}

	tmpl, err := LoadTemplate(
		f,
		func(s string) (io.ReadCloser, error) {
			return testData.Open("testdata/multipage/anchor.jpeg")
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	return mats, tmpl
}

//
// Tests
//

func TestScanPageMat(t *testing.T) {

	//
	// Test that the scan function handles good scans.
	//

	tmpl := loadTestTemplate(t)
	defer tmpl.Close()

	img, err := testData.ReadFile("testdata/input.jpg")
	if err != nil {
		t.Fatal(err)
	}

	mat, err := gocv.IMDecode(img, gocv.IMReadGrayScale)
	if err != nil {
		t.Fatal(err)
	}
	defer mat.Close()

	results, err := scanPageMat(&mat, tmpl, 0)
	if err != nil {
		t.Fatalf("scanPageMat failed: %v", err)
	}
	defer results.Close()

	if results.Picture.Cols() != tmpl.Width ||
		results.Picture.Rows() != tmpl.Height {

		t.Fatalf(
			"expected output %dx%d, got %dx%d",
			tmpl.Width, tmpl.Height,
			results.Picture.Cols(), results.Picture.Rows(),
		)
	}
}

func TestScanPageMatUpsideDown(t *testing.T) {

	//
	// Test that the scan function handles pages that are scanned upside-down.
	//

	tmpl := loadTestTemplate(t)
	defer tmpl.Close()

	img, err := testData.ReadFile("testdata/input.jpg")
	if err != nil {
		t.Fatal(err)
	}

	mat, err := gocv.IMDecode(img, gocv.IMReadGrayScale)
	if err != nil {
		t.Fatal(err)
	}
	defer mat.Close()

	if err := gocv.Flip(mat, &mat, -1); err != nil {
		t.Fatal(err)
	}

	results, err := scanPageMat(&mat, tmpl, 0)
	if err != nil {
		t.Fatalf("scanPageMat failed with flipped scan: %v", err)
	}
	defer results.Close()

	if results.Picture.Cols() != tmpl.Width ||
		results.Picture.Rows() != tmpl.Height {

		t.Fatalf(
			"expected output %dx%d, got %dx%d",
			tmpl.Width, tmpl.Height,
			results.Picture.Cols(), results.Picture.Rows(),
		)
	}
}

func TestScanExamMats(t *testing.T) {

	//
	// Test that a normal two-page exam doesn't err.
	//

	pages, tmpl := loadExamBatch(t)

	const nPagesPerExam = 2

	examData, err := ScanExamMats(pages[:nPagesPerExam], tmpl)
	if err != nil {
		t.Fatal(err)
	}

	//
	// Test that the given page matrices and the returned exams are
	// independent--i.e., that you can close one without closing the other.
	// We test this by closing the pages and then the exams, because if the
	// matrices are the same (bad) then OpenCV will freak the fuck out and
	// explode. Ergo, no explosions means the matrices are independent.
	//

	for i := range nPagesPerExam {
		pages[i].Close()
	}

	examData.Close()
}

func TestScanExamMatsOutOfOrder(t *testing.T) {

	//
	// Test that a two-page exam can be processed even if the pages are given
	// in the wrong order and upside-down.
	//

	pages, tmpl := loadExamBatch(t)
	defer func() {
		for _, page := range pages {
			page.Close()
		}
	}()

	// mess stuff up
	pages[0], pages[1] = pages[1], pages[0]
	gocv.Flip(*pages[0], pages[0], -1)
	gocv.Flip(*pages[1], pages[1], -1)

	exam, err := ScanExamMats(pages[0:2], tmpl)
	if err != nil {
		t.Fatal(err)
	}
	exam.Close()

}

func TestScanMatsBadInputs(t *testing.T) {

	pages, tmpl := loadExamBatch(t)
	defer func() {
		for _, page := range pages {
			page.Close()
		}
	}()

	if _, err := ScanMats(pages[:1], tmpl); err == nil {
		t.Log(
			"ScanMats should fail when the template expects two pages " +
				"and only one is given",
		)
		t.Fail()
	}

	if _, err := ScanMats(pages[:3], tmpl); err == nil {
		t.Log(
			"ScanMats should fail when the number of pages given is not " +
				"divisible by the number of pages in the template",
		)
		t.Fail()
	}

	nilMats := make([]*gocv.Mat, 4)
	if _, err := ScanMats(nilMats, tmpl); err == nil {
		t.Log("ScanMats should fail when given nil matrices")
		t.Fail()
	}

}

func TestScanMatsBatch(t *testing.T) {

	//
	// Test that ScanMats can handle a small batch of exams.
	//

	pages, tmpl := loadExamBatch(t)
	defer func() {
		for _, page := range pages {
			page.Close()
		}
	}()

	exams, err := ScanMats(pages, tmpl)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		for i := range exams {
			exams[i].Close()
		}
	}()

	if len(exams) != 2 {
		t.Fatal("expected 2 exam scans")
	}

	for i := range exams {
		if len(exams[i].Pages) != 2 {
			t.Fatal("expected two pages per exam scan")
		}
	}

}
