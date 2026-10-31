package handler

import (
	"fmt"
	"image"
	"image/draw"
	"io"
	"math"
	"net/http"
	"strconv"
	"ubco-team15/omr/internal/fs"
	"ubco-team15/omr/internal/httpserver/dto"
)

//
// Send an scan's page image.
//

func GetImage(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		//
		// Parse the request information.
		//

		scanId := r.URL.Query().Get("scan")
		if scanId == "" {
			http.Error(
				w,
				"scan query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}

		pageParam := r.URL.Query().Get("page")
		if pageParam == "" {
			http.Error(
				w,
				"page query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}
		pageIdx, err := strconv.Atoi(pageParam)
		if err != nil || pageIdx < 0 {
			http.Error(
				w,
				"page query parameter must be a nonnegative integer",
				http.StatusBadRequest,
			)
			return
		}

		//
		// Access the image.
		//

		img, err := s.OpenScanPicture(scanId, pageIdx)
		if err != nil {
			http.Error(
				w,
				"error retrieving scan image: "+err.Error(),
				http.StatusNotFound,
			)
			return
		}
		defer img.Close()

		//
		// Send the response.
		//

		w.Header().Add("Content-Type", fs.ImgContentType)
		if _, err := io.Copy(w, img); err != nil {
			http.Error(
				w,
				"error writing image to response: "+err.Error(),
				http.StatusInternalServerError,
			)
			return
		}
	}
}

//
// Send a scan's question snippet.
//

func GetSnippet(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		//
		// Parse the request information.
		//

		templateId := r.URL.Query().Get("template")
		if templateId == "" {
			http.Error(
				w,
				"template query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}
		scanId := r.URL.Query().Get("scan")
		if scanId == "" {
			http.Error(
				w,
				"scan query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}
		questionId := r.URL.Query().Get("question")
		if questionId == "" {
			http.Error(
				w,
				"question query parameter is missing",
				http.StatusBadRequest,
			)
			return
		}

		//
		// Get the template and find the identified question.
		//

		tmpl, err := s.LoadMarkingTemplate(templateId)
		if err != nil {
			http.Error(
				w,
				"error loading: "+err.Error(),
				http.StatusNotFound,
			)
			return
		}

		var targetPageIdx int
		var targetQuestion *dto.Question
		for pageIdx := range tmpl.Pages {
			for _, question := range tmpl.Pages[pageIdx].Questions {
				if question.ID == questionId {
					targetPageIdx = pageIdx
					targetQuestion = &question
					break
				}
			}
		}
		if targetQuestion == nil {
			http.Error(
				w,
				fmt.Sprintf("question %s not found", questionId),
				http.StatusNotFound,
			)
			return
		}

		//
		// Load the scan image.
		//

		scan, err := s.LoadScanPicture(scanId, targetPageIdx)
		if err != nil {
			http.Error(
				w,
				"error retrieving scan image: "+err.Error(),
				http.StatusNotFound,
			)
			return
		}

		//
		// Determine the question's bounds in terms of pixels, then build the
		// snippet.
		//

		var (
			minX = math.MaxInt
			minY = math.MaxInt
			maxX = 0
			maxY = 0
		)
		for _, option := range targetQuestion.Options {

			// Note: the X,Y coordinates of an option define the center of it's
			// bubble. In order to get its bounds, we need to add/subtract half
			// of the bubble's respective dimension size.

			minX = min(minX, option.X-targetQuestion.BubbleWidth/2)
			minY = min(minY, option.Y-targetQuestion.BubbleHeight/2)
			maxX = max(maxX, option.X+targetQuestion.BubbleWidth/2)
			maxY = max(maxY, option.Y+targetQuestion.BubbleHeight/2)

		}

		const padding = 10
		minX -= padding
		maxX += padding
		minY -= padding
		maxY += padding

		rect := image.Rect(0, 0, maxX-minX, maxY-minY)
		snippet := image.NewRGBA(rect)
		draw.Draw(
			snippet,
			rect,
			scan,
			image.Point{X: minX, Y: minY},
			draw.Src,
		)

		//
		// Send the snippet.
		//

		w.Header().Add("Content-Type", fs.ImgContentType)
		if err := fs.EncodeImg(w, snippet); err != nil {
			http.Error(
				w,
				"error writing image to response: "+err.Error(),
				http.StatusInternalServerError,
			)
			return
		}
	}
}
