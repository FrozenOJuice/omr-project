package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"ubco-team15/omr/internal/httpserver/dto"
)

//
// Helper functions
//

func newScanPdfRequest(
	t *testing.T,
	pTmplId string,
	pdfPath string,
	dpi string,
) *http.Request {
	t.Helper()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	if pTmplId != "" {
		err := writer.WriteField("preprocessingTemplate", pTmplId)
		if err != nil {
			t.Fatal(err)
		}
	}

	if dpi != "" {
		err := writer.WriteField("dpi", dpi)
		if err != nil {
			t.Fatal(err)
		}
	}

	if pdfPath != "" {
		part, err := writer.CreateFormFile("pdf", "exams.pdf")
		if err != nil {
			t.Fatal(err)
		}

		buf, err := testData.ReadFile(pdfPath)
		if err != nil {
			t.Fatal(err)
		}

		if _, err := part.Write(buf); err != nil {
			t.Fatal(err)
		}
	}

	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest(
		http.MethodPost,
		"/",
		&body,
	)
	req.Header.Set("Content-Type", writer.FormDataContentType())

	return req
}

// Get the marks for scans and return the results.
func getMarkResults(
	t *testing.T,
	s ServerResources,
	scanIds []string,
	mTmplId string,
) *dto.MarkingResult {

	scanList := strings.Builder{}
	scanList.WriteString("[")
	for i, scanId := range scanIds {
		fmt.Fprintf(&scanList, "\"%s\"", scanId)
		if i != len(scanIds)-1 {
			scanList.WriteString(",")
		}
	}
	scanList.WriteString("]")

	body := fmt.Appendf(nil,
		`{
			"template": "%s",
			"scans": %s
		}`,
		mTmplId,
		scanList.String(),
	)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	PostMarkingJob(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	marks := &dto.MarkingResult{}
	if err := json.Unmarshal(rr.Body.Bytes(), marks); err != nil {
		t.Fatal("failed to unmarshal response body")
	}

	return marks
}

//
// Tests
//

func TestPostScanPdfSync_Normal(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)

	//
	// Normal path
	//

	req := newScanPdfRequest(t, pTmplId, "testdata/batches/3_normal_exams.pdf", "")
	rr := httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

}

func TestPostScanPdfSync_Funky(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)

	//
	// Test an exam that has some pages in the wrong order and upside-down.
	//

	req := newScanPdfRequest(t, pTmplId, "testdata/batches/1_funky_exam.pdf", "")
	rr := httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

}

func TestPostScanPdfSync_FunkyBatch(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)
	mTmplId := postNewMarkingTemplate(t, s)

	//
	// This test uploads some PDF scans that have some funkiness (some pages
	// are upside-down, some are in the wrong order), but they're all the same
	// exam. This means that we should be able to verify that the exams were
	// parsed correctly by marking them after their upload and then checking
	// whether the markings are equal.
	//

	req := newScanPdfRequest(
		t,
		pTmplId,
		"testdata/batches/5_funky_duplicate_exams.pdf",
		"",
	)
	rr := httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	var scanResult dto.ScanResult
	json.Unmarshal(rr.Body.Bytes(), &scanResult)

	if len(scanResult.Errors) != 0 {
		errors, _ := json.MarshalIndent(scanResult.Errors, "", "  ")
		t.Fatalf(
			"expected no errors in preprocessing; got\n\n"+
				"%v\n\n",
			errors,
		)
	}

	marks := getMarkResults(t, s, scanResult.ScanIds, mTmplId)
	for i := 1; i < len(marks.Scans); i++ {

		marksA, marksB := marks.Scans[i].Marks, marks.Scans[i-1].Marks
		if len(marksA) != len(marksB) {
			t.Fatalf(
				"returned marks have different lengths (%d and %d)",
				len(marksA), len(marksB),
			)
		}

		for j := range marksA {
			a, b := marksA[j], marksB[j]
			switch {
			case a.QuestionId != b.QuestionId,
				a.Flagged != b.Flagged,
				!reflect.DeepEqual(a.Selected, b.Selected):

				aStr, _ := json.MarshalIndent(a, "  ", "  ")
				bStr, _ := json.MarshalIndent(b, "  ", "  ")

				t.Fatalf(
					"Mismatch between marks returned for scans %d and %d:\n"+
						"\n"+
						"Scan %d, Mark %d:\n"+
						"%s\n"+
						"\n"+
						"Scan %d, Mark %d:\n"+
						"%s\n"+
						"\n",
					i, i-1,
					i, j,
					string(aStr),
					i-1, j,
					string(bStr),
				)
			}
		}
	}
}

func TestPostScanPdfSync_BadInputs(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)

	//
	// This test just runs through a set of bad inputs to the endpoint.
	//

	// 400: No template ID.
	req := newScanPdfRequest(t, "", "testdata/batches/1_funky_exam.pdf", "")

	rr := httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	// 400: No PDF.
	req = newScanPdfRequest(t, pTmplId, "", "")

	rr = httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	// 400: Malformed PDF.
	req = newScanPdfRequest(t, pTmplId, "testdata/pages/exam0page0.jpeg", "")

	rr = httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	// 400: Page count mismatch between scan and template.
	req = newScanPdfRequest(
		t, pTmplId, "testdata/batches/1_half_of_an_exam.pdf", "",
	)

	rr = httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	// 404: Unrecognized template ID.
	req = newScanPdfRequest(
		t, "big chungus", "testdata/batches/1_funky_exam.pdf", "",
	)

	rr = httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}
}

func TestPostScanPdfSync_FailedPreprocessing(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)

	//
	// When sending PDFs to the OMR, using a DPI that's too low will make it
	// impossible for the preprocessor to make sense of them. In this case we
	// expect all scans to fail which should give us a status of 422.
	//

	req := newScanPdfRequest(
		t,
		pTmplId,
		"testdata/batches/5_funky_duplicate_exams.pdf",
		"50",
	)
	rr := httptest.NewRecorder()
	PostScanPdfSync(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	var scanResult []dto.ScanError
	json.Unmarshal(rr.Body.Bytes(), &scanResult)

	if len(scanResult) != 5 {
		t.Fatalf(
			"expected 5 errors in preprocessing; got %d",
			len(scanResult),
		)
	}

}
