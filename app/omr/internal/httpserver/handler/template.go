package handler

import (
	"fmt"
	"io"
	"net/http"

	"ubco-team15/omr/internal/httpserver/dto"
	"ubco-team15/omr/internal/scanner"

	"gocv.io/x/gocv"
)

const maxUploadSize = 32 * 1024 * 1024 // 32 MB

//
// Marking templates
//

func PostMarkingTemplate(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		defer r.Body.Close()
		jsonBuf, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(
				w, "error reading body: "+err.Error(), http.StatusBadRequest,
			)
			return
		}

		tmpl, err := dto.ParseMarkingTemplate(jsonBuf)
		if err != nil {
			http.Error(
				w, "error parsing body: "+err.Error(), http.StatusBadRequest,
			)
			return
		}

		id, err := s.SaveMarkingTemplate(tmpl)
		if err != nil {
			http.Error(
				w, "error saving template: "+err.Error(),
				http.StatusInternalServerError,
			)
			return
		}

		dto.SendJson(w, map[string]string{
			"templateId": id,
		})
	}
}

func DeleteMarkingTemplate(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(
				w,
				"id query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}

		s.DeleteMarkingTemplate(id)

		w.WriteHeader(http.StatusOK)

	}
}

//
// Preprocessing templates
//

func PostPreprocessingTemplate(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		defer r.Body.Close()
		if err := r.ParseMultipartForm(maxUploadSize); err != nil {
			http.Error(w, "invalid multipart form", http.StatusBadRequest)
			return
		}

		jsonBuf := r.FormValue("template")
		tmpl, err := dto.ParsePreprocessingTemplate([]byte(jsonBuf))
		if err != nil {
			http.Error(
				w,
				"error parsing template: "+err.Error(),
				http.StatusBadRequest,
			)
			return
		}

		templateId, err := s.SavePreprocessingTemplate(tmpl)
		if err != nil {
			http.Error(
				w, "error saving template: "+err.Error(),
				http.StatusInternalServerError,
			)
			return
		}

		binarizeConf := &scanner.Config{
			BlurSize:            tmpl.Config.BlurSize,
			MorphCloseSize:      tmpl.Config.MorphCloseSize,
			MinAnchorConfidence: float32(tmpl.Config.MinAnchorConfidence),
			AdaptiveBlockSize:   tmpl.Config.AdaptiveBlockSize,
			AdaptiveC:           float32(tmpl.Config.AdaptiveC),
		}

		for i := range tmpl.Pages {
			for j := range tmpl.Pages[i].Anchors {
				fileKey := fmt.Sprintf("page%danchor%d", i, j)
				f, _, err := r.FormFile(fileKey)
				if err != nil {
					http.Error(
						w,
						"expected anchor image file "+fileKey,
						http.StatusBadRequest,
					)
					return
				}
				defer f.Close()

				buf, err := io.ReadAll(f)
				if err != nil {
					http.Error(
						w,
						"unexpected read error: "+err.Error(),
						http.StatusInternalServerError,
					)
					return
				}

				mat, err := gocv.IMDecode(buf, gocv.IMReadGrayScale)
				if err != nil {
					http.Error(
						w,
						"failed to decode "+fileKey+" as an image",
						http.StatusBadRequest,
					)
					return
				}
				defer mat.Close()

				err = scanner.Binarize(&mat, &mat, binarizeConf)
				if err != nil {
					http.Error(
						w,
						"error preprocessing anchor "+fileKey+": ",
						http.StatusInternalServerError,
					)
					return
				}

				if err := s.SaveAnchor(&mat, templateId, i, j); err != nil {
					http.Error(
						w,
						fmt.Sprintf(
							"error saving anchor image page%danchor%d",
							i, j,
						),
						http.StatusInternalServerError,
					)
					return
				}
			}
		}

		dto.SendJson(w, map[string]string{
			"templateId": templateId,
		})
	}
}

func DeletePreprocessingTemplate(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(
				w,
				"id query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}

		s.DeletePreprocessingTemplate(id)

		w.WriteHeader(http.StatusOK)

	}
}
