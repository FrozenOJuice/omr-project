package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"ubco-team15/omr/internal/httpserver/dto"
)

//
// Helper functions
//
// Since the marking endpoint relies on the functionality of the other
// endpoints (namely, uploading a preprocessing template, a scan, and then a
// marking template), these helpers simply carry out those requests in a way
// that we expect to succeed. These helpers don't return errors; instead they
// fail the test if something goes wrong.
//

// Persists a new preprocessing template and returns the ID for it.
func postNewPreprocessingTemplate(t *testing.T, s ServerResources) string {
	req, err := makeMultipartRequest(
		t,
		"testdata/preprocessing_template.json",
		multipartImage{
			name:     "page0anchor0",
			filename: "testdata/anchors/anchor.jpeg",
		},
		multipartImage{
			name:     "page0anchor1",
			filename: "testdata/anchors/anchor.jpeg",
		},
		multipartImage{
			name:     "page0anchor2",
			filename: "testdata/anchors/anchor.jpeg",
		},
		multipartImage{
			name:     "page1anchor0",
			filename: "testdata/anchors/anchor.jpeg",
		},
		multipartImage{
			name:     "page1anchor1",
			filename: "testdata/anchors/anchor.jpeg",
		},
		multipartImage{
			name:     "page1anchor2",
			filename: "testdata/anchors/anchor.jpeg",
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()

	PostPreprocessingTemplate(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatal("failed to upload preprocessing template")
	}

	v := make(map[string]string)
	if err := json.Unmarshal(rr.Body.Bytes(), &v); err != nil {
		t.Fatal("failed to parse JSON response: " + err.Error())
	}
	preprocessingTemplateId, ok := v["templateId"]
	if !ok {
		t.Fatal("templateId wasn't found in response body")
	}

	return preprocessingTemplateId
}

// Persists a new exam scan and returns the ID for it.
func postNewScan(t *testing.T, s ServerResources, pTmplId string) string {
	req, err := makeMultipartRequest(
		t,
		"",
		multipartImage{
			name:     "page0",
			filename: "testdata/pages/exam0page0.jpeg",
		},
		multipartImage{
			name:     "page1",
			filename: "testdata/pages/exam0page1.png",
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	req.URL.RawQuery += "template=" + pTmplId

	rr := httptest.NewRecorder()
	PostScan(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	v := make(map[string]string)
	if err := json.Unmarshal(rr.Body.Bytes(), &v); err != nil {
		t.Fatalf("failed to parse JSON response: %s", err.Error())
	}
	scanId, ok := v["scanId"]
	if !ok {
		t.Fatalf("scanId wasn't found in response body")
	}

	return scanId
}

// Persists a new marking template and returns the ID for it.
func postNewMarkingTemplate(t *testing.T, s ServerResources) string {
	req, err := makeJsonRequest(t, "testdata/marking_template.json")
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()
	PostMarkingTemplate(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body%s", rr.Code, rr.Body.String())
	}

	v := make(map[string]string)
	if err := json.Unmarshal(rr.Body.Bytes(), &v); err != nil {
		t.Fatalf("failed to parse JSON response: %s", err.Error())
	}
	markingTemplateId, ok := v["templateId"]
	if !ok {
		t.Fatalf("templateId wasn't found in response body")
	}

	return markingTemplateId
}

//
// Tests
//

func TestPostMark(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	//
	// The setup for the marking endpoint requires using a couple other
	// endpoints. The steps are:
	//
	//  1) Upload the preprocessing template.
	//  2) Upload the scan(s) of the exam.
	//  3) Upload the marking template.
	//  4) Post the marking job.
	//
	// After that, we can check that the marks are what we expect.
	//

	pTmplId := postNewPreprocessingTemplate(t, s) // (1)
	scanId := postNewScan(t, s, pTmplId)          // (2)
	mTmplId := postNewMarkingTemplate(t, s)       // (3)

	//
	// 4) Post the marking job.
	//

	body := fmt.Appendf(nil,
		`{
			"template": "%s",
			"scans": [
				"%s"
			]
		}`,
		mTmplId,
		scanId,
	)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	PostMarkingJob(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	//
	// Check the marks.
	//

	actual := &dto.MarkingResult{}
	if err := json.Unmarshal(rr.Body.Bytes(), actual); err != nil {
		t.Fatal("failed to unmarshal response body")
	}

	expected := &dto.MarkingResult{}
	buf, err := testData.ReadFile("testdata/answers/exam0.json")
	if err != nil {
		t.Fatal("failed to read answers file")
	}
	if err := json.Unmarshal(buf, expected); err != nil {
		t.Fatalf("failed to unmarshal answers file")
	}

	if len(actual.Scans) == 0 {
		t.Fatal("response body had no scans")
	}
	if len(expected.Scans) != len(actual.Scans) {
		t.Fatalf(
			"expected %d scans but got %d",
			len(expected.Scans), len(actual.Scans),
		)
	}

	for i := range actual.Scans {
		if actual.Scans[i].ScanId != scanId {
			t.Fatalf(
				"expected result scanId to be %s, got %s",
				scanId, actual.Scans[i].ScanId,
			)
		}
		if len(expected.Scans[i].Marks) != len(actual.Scans[i].Marks) {
			t.Fatalf(
				"expected %d scans but got %d",
				len(expected.Scans), len(actual.Scans),
			)
		}

		// Note: this current test expects answers to be in a specific order,
		// but that's not actually important. We can remove that constraint
		// later if it becomes relevant.
		for j := range len(actual.Scans[i].Marks) {
			actualMark := actual.Scans[i].Marks[j]
			expectedMark := expected.Scans[i].Marks[j]
			if actualMark.QuestionId != expectedMark.QuestionId {
				t.Fatal("question ID mismatch")
			}
			if actualMark.Flagged != expectedMark.Flagged {
				t.Fatalf(
					"question %s: expected flagged=%t, got flagged=%t",
					actualMark.QuestionId,
					expectedMark.Flagged,
					actualMark.Flagged,
				)
			}
			if len(actualMark.Selected) != len(expectedMark.Selected) {
				t.Fatalf(
					"question %s: expected %d selections, got %d",
					actualMark.QuestionId,
					len(expectedMark.Selected),
					len(actualMark.Selected),
				)
			}

			for k := range len(actualMark.Selected) {
				if actualMark.Selected[k] != expectedMark.Selected[k] {
					t.Fatalf(
						"question %s: expected selection %s, got %s",
						actualMark.QuestionId,
						expectedMark.Selected[k],
						actualMark.Selected[k],
					)
				}
			}
		}
	}
}

// A batch with one good scan and one bogus scan ID should still mark the
// good scan and report the bogus one in errors, rather than aborting the
// whole request.
func TestPostMarkPartialFailure(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	pTmplId := postNewPreprocessingTemplate(t, s)
	scanId := postNewScan(t, s, pTmplId)
	mTmplId := postNewMarkingTemplate(t, s)

	body := fmt.Appendf(nil,
		`{
			"template": "%s",
			"scans": [
				"%s",
				"does-not-exist"
			]
		}`,
		mTmplId,
		scanId,
	)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	PostMarkingJob(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	actual := &dto.MarkingResult{}
	if err := json.Unmarshal(rr.Body.Bytes(), actual); err != nil {
		t.Fatal("failed to unmarshal response body")
	}

	if len(actual.Scans) != 1 {
		t.Fatalf("expected 1 successfully marked scan, got %d", len(actual.Scans))
	}
	if actual.Scans[0].ScanId != scanId {
		t.Fatalf("expected result scanId to be %s, got %s", scanId, actual.Scans[0].ScanId)
	}
	if len(actual.Errors) != 1 {
		t.Fatalf("expected 1 error, got %d", len(actual.Errors))
	}
	if actual.Errors[0].ScanId != "does-not-exist" {
		t.Fatalf("expected error scanId to be does-not-exist, got %s", actual.Errors[0].ScanId)
	}
}

// A batch where every scan ID is bogus should 422 with an error per scan,
// and no partial 200.
func TestPostMarkAllScansFail(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	mTmplId := postNewMarkingTemplate(t, s)

	body := fmt.Appendf(nil,
		`{
			"template": "%s",
			"scans": [
				"does-not-exist-1",
				"does-not-exist-2"
			]
		}`,
		mTmplId,
	)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	PostMarkingJob(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	var actual []dto.MarkingError
	if err := json.Unmarshal(rr.Body.Bytes(), &actual); err != nil {
		t.Fatal("failed to unmarshal response body")
	}
	if len(actual) != 2 {
		t.Fatalf("expected 2 errors, got %d", len(actual))
	}
}
