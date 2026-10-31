package handler

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"ubco-team15/omr/internal/fs"
	"ubco-team15/omr/internal/httpserver/dto"
)

func TestGetImage(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	//
	// Setup
	//

	pTmplId := postNewPreprocessingTemplate(t, s)
	scanId := postNewScan(t, s, pTmplId)

	//
	// Get the page images.
	//

	badQueries400 := []string{
		"",
		"scan=" + scanId,
		"page=0",
		"scan=" + scanId + "&page=notanumber",
	}
	for _, query := range badQueries400 {
		req, err := http.NewRequest(http.MethodGet, "/", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.URL.RawQuery = query
		rr := httptest.NewRecorder()
		GetImage(s).ServeHTTP(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Fatalf(
				"expected query %s to have 400 response, got %d",
				query, rr.Code,
			)
		}
	}

	badQueries404 := []string{
		"scan=1234&page=0",
		"scan=" + scanId + "&page=99",
	}
	for _, query := range badQueries404 {
		req, err := http.NewRequest(http.MethodGet, "/", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.URL.RawQuery = query
		rr := httptest.NewRecorder()
		GetImage(s).ServeHTTP(rr, req)

		if rr.Code != http.StatusNotFound {
			t.Fatalf(
				"expected query %s to have 404 response, got %d",
				query, rr.Code,
			)
		}
	}

	for pageIdx := range 2 {
		req, err := http.NewRequest(http.MethodGet, "/", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.URL.RawQuery = fmt.Sprintf("scan=%s&page=%d", scanId, pageIdx)
		rr := httptest.NewRecorder()
		GetImage(s).ServeHTTP(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf(
				"expected query %s to have 200 response, got %d",
				req.URL.RawQuery, rr.Code,
			)
		}
		if ct := rr.Header().Get("Content-Type"); ct != fs.ImgContentType {
			t.Fatalf("expected Content-Type %s, got %s", fs.ImgContentType, ct)
		}
		if rr.Body.Len() == 0 {
			t.Fatalf("expected a non-empty image body for page %d", pageIdx)
		}
	}
}

//
// Snippet tests
//

func TestGetSnippet(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	//
	// We need some setup before we can get snippets. Namely,
	//
	//  1) Upload the preprocessing template.
	//  2) Upload the scan(s) of the exam.
	//  3) Upload the marking template.
	// 	4) Get snippets.
	//
	// It's not straightforward to test whether the question snippets are
	// correct without looking at them, so for this test we just confirm that
	// there is a snippet returned for each question.
	//

	pTmplId := postNewPreprocessingTemplate(t, s)
	scanId := postNewScan(t, s, pTmplId)
	mTmplId := postNewMarkingTemplate(t, s)

	//
	// 4) Get the snippets.
	//

	// Some queries we expect to return 400 because the request is missing
	// information.
	badQueries400 := []string{
		"",
		"question=1234",
		"question=1234&scan=1234",
		"question=1234&template=1234",
	}
	for _, query := range badQueries400 {
		req, err := http.NewRequest(http.MethodGet, "/", nil)
		if err != nil {
			t.Fatal(err)
		}

		req.URL.RawQuery = query
		rr := httptest.NewRecorder()
		GetSnippet(s).ServeHTTP(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Fatalf(
				"expected query %s to have 400 response, got %d",
				query,
				rr.Code,
			)
		}
	}

	// Some queries we expect to return 404 because the requested resources are
	// missing.
	badQueries404 := []string{
		"question=1234&scan=1234&template=1234",
		"question=1234&scan=" + scanId + "&template=1234",
		"question=1234&scan=1234&template=" + mTmplId,
	}
	for _, query := range badQueries404 {
		req, err := http.NewRequest(http.MethodGet, "/", nil)
		if err != nil {
			t.Fatal(err)
		}

		req.URL.RawQuery = query
		rr := httptest.NewRecorder()
		GetSnippet(s).ServeHTTP(rr, req)

		if rr.Code != http.StatusNotFound {
			t.Fatalf(
				"expected query %s to have 404 response, got %d",
				query,
				rr.Code,
			)
		}
	}

	// Now, we test all requests we expect to be 200.

	buf, err := testData.ReadFile("testdata/marking_template.json")
	var tmpl dto.MarkingTemplate
	if err := json.Unmarshal(buf, &tmpl); err != nil {
		t.Fatal("error parsing marking template: " + err.Error())
	}

	for _, page := range tmpl.Pages {
		for _, question := range page.Questions {

			req, err := http.NewRequest(http.MethodGet, "/", nil)
			if err != nil {
				t.Fatal(err)
			}

			req.URL.RawQuery = fmt.Sprintf(
				"question=%s&scan=%s&template=%s",
				question.ID, scanId, mTmplId,
			)
			rr := httptest.NewRecorder()
			GetSnippet(s).ServeHTTP(rr, req)

			if rr.Code != http.StatusOK {
				t.Fatalf(
					"expected query %s to have 200 response, got %d",
					req.URL.RawQuery,
					rr.Code,
				)
			}

		}
	}
}
