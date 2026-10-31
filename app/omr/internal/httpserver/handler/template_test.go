package handler

import (
	"bytes"
	"embed"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

//
// Helper functions.
//

//go:embed testdata/*
var testData embed.FS

type multipartImage struct {
	name     string
	filename string
}

func makeJsonRequest(
	t *testing.T,
	templateFilename string,
) (*http.Request, error) {
	t.Helper()

	template, err := testData.Open(templateFilename)
	if err != nil {
		return nil, err
	}
	defer template.Close()

	req := httptest.NewRequest(http.MethodPost, "/", template)
	req.Header.Set("Content-Type", "application/json")

	return req, nil
}

func makeMultipartRequest(
	t *testing.T,
	templateFilename string,
	images ...multipartImage,
) (*http.Request, error) {
	t.Helper()

	var body bytes.Buffer
	w := multipart.NewWriter(&body)

	if templateFilename != "" {
		template, err := testData.ReadFile(templateFilename)
		if err != nil {
			return nil, err
		}

		if err := w.WriteField("template", string(template)); err != nil {
			return nil, err
		}
	}

	for _, image := range images {
		imgWriter, err := w.CreateFormFile(image.name, image.name)
		if err != nil {
			return nil, err
		}
		f, err := testData.Open(image.filename)
		if err != nil {
			return nil, err
		}
		defer f.Close()

		if _, err := io.Copy(imgWriter, f); err != nil {
			return nil, err
		}
	}

	if err := w.Close(); err != nil {
		return nil, err
	}

	req := httptest.NewRequest(http.MethodPost, "/", &body)
	req.Header.Set("Content-Type", w.FormDataContentType())

	return req, nil
}

//
// Tests.
//

func TestPostPreprocessingTemplate_OK(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

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
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}

	v := make(map[string]string)
	if err := json.Unmarshal(rr.Body.Bytes(), &v); err != nil {
		t.Fatalf("failed to parse JSON response: %s", err.Error())
	}
	templateId, ok := v["templateId"]
	if !ok {
		t.Fatalf("templateId wasn't found in response body")
	}

	if _, err := s.LoadPreprocessingTemplate(templateId); err != nil {
		t.Fatal("Preprocessing template not found in database")
	}

	savedAnchors, err := s.LoadAnchors(templateId)
	if err != nil {
		t.Fatal(err)
	}

	const pageCount = 2
	const anchorsPerPage = 3

	if len(savedAnchors) != pageCount {
		t.Fatalf(
			"only found saved anchors for %d page(s), expected %d",
			len(savedAnchors), pageCount,
		)
	}
	for i := range savedAnchors {
		if len(savedAnchors[i]) != anchorsPerPage {
			t.Fatalf(
				"only found %d saved anchors for page %d, expected %d",
				len(savedAnchors[i]), i, anchorsPerPage,
			)
		}
	}
}

func TestPostPreprocessingTemplate_BAD1(t *testing.T) {

	//
	// This request should be bad because the template specifies two pages,
	// but the request only has enough anchors for one.
	//

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

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
	)
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()

	PostPreprocessingTemplate(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}
}

func TestPostPreprocessingTemplate_BAD2(t *testing.T) {

	//
	// This request should be bad because there's only 2 anchors for one of
	// the pages.
	//

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

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
	)
	if err != nil {
		t.Fatal(err)
	}

	rr := httptest.NewRecorder()
	PostPreprocessingTemplate(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
	}
}

func TestPostMarkingTemplate_OK(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

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
	templateId, ok := v["templateId"]
	if !ok {
		t.Fatalf("templateId wasn't found in response body")
	}

	if _, err := s.LoadMarkingTemplate(templateId); err != nil {
		t.Log(err)
		t.Fatal("Preprocessing template not found in database")
	}
}

func TestDeletePreprocessingTemplate(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	templateID := postNewPreprocessingTemplate(t, s)

	tests := []struct {
		name       string
		templateID string
		wantStatus int
	}{
		{
			name:       "missing id",
			templateID: "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "template not found",
			templateID: "do you belieeeeve in life after looove",
			wantStatus: http.StatusOK,
		},
		{
			name:       "normal path",
			templateID: templateID,
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(
				http.MethodDelete,
				"/template/preprocess?id="+url.QueryEscape(tt.templateID),
				nil,
			)

			rr := httptest.NewRecorder()
			DeletePreprocessingTemplate(s).ServeHTTP(rr, req)

			if rr.Code != tt.wantStatus {
				t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
			}

			if tt.name == "normal path" {
				if _, err := s.LoadPreprocessingTemplate(templateID); err == nil {
					t.Fatal("template still exists after deletion")
				}
			}
		})
	}
}

func TestDeleteMarkingTemplate(t *testing.T) {

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	templateID := postNewMarkingTemplate(t, s)

	tests := []struct {
		name       string
		templateID string
		wantStatus int
	}{
		{
			name:       "missing id",
			templateID: "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "template not found",
			templateID: "i can feel something inside me say, 'I really don't think it's strong enough noo'",
			wantStatus: http.StatusOK,
		},
		{
			name:       "normal path",
			templateID: templateID,
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(
				http.MethodDelete,
				"/template/mark?id="+url.QueryEscape(tt.templateID),
				nil,
			)

			rr := httptest.NewRecorder()
			DeleteMarkingTemplate(s).ServeHTTP(rr, req)

			if rr.Code != tt.wantStatus {
				t.Fatalf("status=%d body=%s", rr.Code, rr.Body.String())
			}

			if tt.name == "normal path" {
				if _, err := s.LoadMarkingTemplate(templateID); err == nil {
					t.Fatal("template still exists after deletion")
				}
			}
		})
	}
}
