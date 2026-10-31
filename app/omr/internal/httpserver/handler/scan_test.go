package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"ubco-team15/omr/internal/httpserver/dto"
)

//
// Helper functions
//

// Fails the test unless the response is an error with the specified reason.
func assertError(
	t *testing.T,
	rr *httptest.ResponseRecorder,
	e dto.ErrReason,
) {
	t.Helper()

	body := make(map[string]string)
	json.Unmarshal(rr.Body.Bytes(), &body)

	if reason := body["code"]; reason != string(e) {
		t.Fatalf("expected error reason %v, got %s", e, reason)
	}
}

//
// Tests
//

func TestPostScan(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	//
	// Uploading scans requires that we first have a preprocessing template.
	//

	templateId := postNewPreprocessingTemplate(t, s)

	//
	// Now we can try to post the scan. We'll test out a couple of error cases
	// and then the normal path.
	//

	tests := []struct {
		name       string
		templateID string
		pages      []multipartImage
		wantStatus int
		wantError  dto.ErrReason
	}{
		{
			name:       "no pages",
			templateID: templateId,
			wantStatus: http.StatusBadRequest,
			wantError:  dto.ErrPageCountMismatch,
		},
		{
			name:       "wrong number of pages",
			templateID: templateId,
			pages: []multipartImage{
				{
					name:     "page0",
					filename: "testdata/pages/exam0page0.jpeg",
				},
			},
			wantStatus: http.StatusBadRequest,
			wantError:  dto.ErrPageCountMismatch,
		},
		{
			name:       "unrecognized template",
			templateID: "chickenturtleduck",
			pages: []multipartImage{
				{
					name:     "page0",
					filename: "testdata/pages/exam0page0.jpeg",
				},
				{
					name:     "page1",
					filename: "testdata/pages/exam0page1.png",
				},
			},
			wantStatus: http.StatusNotFound,
			wantError:  dto.ErrTemplateNotFound,
		},
		{
			name:       "normal path",
			templateID: templateId,
			pages: []multipartImage{
				{
					name:     "page0",
					filename: "testdata/pages/exam0page0.jpeg",
				},
				{
					name:     "page1",
					filename: "testdata/pages/exam0page1.png",
				},
			},
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req, err := makeMultipartRequest(t, "", tt.pages...)
			if err != nil {
				t.Fatal(err)
			}

			req.URL.RawQuery = "template=" + tt.templateID

			rr := httptest.NewRecorder()
			PostScan(s).ServeHTTP(rr, req)

			if rr.Code != tt.wantStatus {
				t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
			}

			if tt.wantError != "" {
				assertError(t, rr, tt.wantError)
				return
			}

			var v struct {
				ScanID string `json:"scanId"`
			}

			if err := json.Unmarshal(rr.Body.Bytes(), &v); err != nil {
				t.Fatalf("failed to parse JSON response: %s", err)
			}

			if v.ScanID == "" {
				t.Fatal("scanId wasn't found in response body")
			}

			pages, err := s.LoadScan(v.ScanID)
			if err != nil {
				t.Fatalf("scan wasn't saved: %s", err)
			}
			defer func() {
				for _, page := range pages {
					page.Close()
				}
			}()

			if len(pages) != 2 {
				t.Fatalf("got %d pages, want 2", len(pages))
			}
		})
	}
}

func TestDeleteScan(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	//
	// Uploading scans requires that we first have a preprocessing template.
	//

	pTemplId := postNewPreprocessingTemplate(t, s)

	//
	// Upload a few scans.
	//

	keepID := postNewScan(t, s, pTemplId)
	deleteID1 := postNewScan(t, s, pTemplId)
	deleteID2 := postNewScan(t, s, pTemplId)

	//
	// Verify they exist before deletion.
	//

	for _, id := range []string{keepID, deleteID1, deleteID2} {
		pages, err := s.LoadScan(id)
		if err != nil {
			t.Fatalf("scan %s was not created: %s", id, err)
		}

		for _, page := range pages {
			page.Close()
		}

		if _, err := s.LoadScanPicture(id, 0); err != nil {
			t.Fatalf("scan picture %s was not created: %s", id, err)
		}
	}

	//
	// Delete two scans.
	//

	body := dto.ScanDeleteRequest{deleteID1, deleteID2}
	jsonBuf, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("failed to serialize request body: %s", err.Error())
	}
	req := httptest.NewRequest(
		http.MethodDelete,
		"/scans",
		bytes.NewReader(jsonBuf),
	)

	rr := httptest.NewRecorder()
	DeleteScans(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("delete failed: status=%d body=%s", rr.Code, rr.Body.String())
	}

	//
	// Deleted scans should no longer exist.
	//

	for _, id := range []string{deleteID1, deleteID2} {
		pages, err := s.LoadScan(id)
		if err == nil {
			for _, page := range pages {
				page.Close()
			}
			t.Fatalf("deleted scan %s still exists", id)
		}

		if _, err := s.LoadScanPicture(id, 0); err == nil {
			t.Fatalf("deleted scan picture %s still exists", id)
		}
	}

	//
	// Non-deleted scan should still exist.
	//

	pages, err := s.LoadScan(keepID)
	if err != nil {
		t.Fatalf("undeleted scan disappeared: %s", err)
	}

	for _, page := range pages {
		page.Close()
	}

	if _, err := s.LoadScanPicture(keepID, 0); err != nil {
		t.Fatalf("undeleted scan picture disappeared: %s", err)
	}
}
