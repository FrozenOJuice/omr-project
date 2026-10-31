package handler

import (
	"fmt"
	"io"
	"net/http"
	"runtime"
	"sync"
	"sync/atomic"

	"ubco-team15/omr/internal/httpserver/dto"
	"ubco-team15/omr/internal/marker"
	"ubco-team15/omr/internal/sys"

	"gocv.io/x/gocv"
)

type scan struct {
	id     string
	pages  []*gocv.Mat
	closed bool
}

// Idempotently closes the scan's pages.
func (s *scan) close() {
	if s.closed {
		return
	}

	for i := range s.pages {
		s.pages[i].Close()
	}
	s.closed = true
}

func PostMarkingJob(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		//
		// Parse the request.
		//

		defer sys.Tidy()
		defer r.Body.Close()

		jsonBuf, err := io.ReadAll(r.Body)
		if err != nil {
			dto.SendError(
				w,
				http.StatusBadRequest,
				dto.ErrInvalidRequest,
				"error reading body: "+err.Error(),
			)
			return
		}

		markingJob, err := dto.ParseMarkingJobRequest(jsonBuf)
		if err != nil {
			dto.SendError(
				w,
				http.StatusBadRequest,
				dto.ErrInvalidRequest,
				"error parsing body: "+err.Error(),
			)
			return
		}

		//
		// Fetch the required resources.
		//

		t, err := s.LoadMarkingTemplate(markingJob.TemplateId)
		if err != nil {
			dto.SendError(
				w,
				http.StatusNotFound,
				dto.ErrTemplateNotFound,
				"error retrieving template: "+err.Error(),
			)
			return
		}
		template := dto.AdaptMarkerTemplate(t)

		//
		// We stream the scans and mark them in parallel. This sets a limit
		// on the number of scans that are kept in memory at a given time.
		// A single scan's failure (a missing scan, a page count mismatch,
		// a marking failure, or a panic) is attached to that scan instead
		// of aborting the whole batch, mirroring how POST /scan/pdf reports
		// partial batch failures.
		//

		nextIdx := atomic.Uint32{}
		nScans := len(markingJob.ScanIds)

		scans := make([]dto.Scan, nScans)
		errs := make([]*dto.MarkingError, nScans)

		wg := sync.WaitGroup{}
		for range runtime.GOMAXPROCS(0) {
			wg.Go(func() {

				//
				// Each thread runs until the pool of scan IDs is exhausted.
				//

				for {
					idx := nextIdx.Add(1) - 1
					if int(idx) >= nScans {
						break
					}
					scanId := markingJob.ScanIds[idx]

					if err := markScan(s, template, scanId, &scans[idx]); err != nil {
						errs[idx] = &dto.MarkingError{ScanId: scanId, Debug: err.Error()}
					}
				}
			})
		}
		wg.Wait()

		result := dto.NewMarkingResult(
			markingJob.TemplateId, len(template.Pages), scans, errs,
		)

		switch {
		case len(result.Scans) == 0:
			// Every scan in the batch failed to mark.
			w.WriteHeader(http.StatusUnprocessableEntity)
			dto.SendCompressedJson(w, r, result.Errors)
		default:
			dto.SendCompressedJson(w, r, result)
		}
	}
}

// markScan marks a single scan against the given template, writing the
// result into *out on success. On failure, including a panic while marking
// (which would otherwise crash the whole process, since it happens on a
// goroutine the top-level recovery middleware can't see), it returns a
// non-nil error describing what went wrong, and *out is left untouched.
func markScan(
	s ServerResources,
	template *marker.Template,
	scanId string,
	out *dto.Scan,
) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic while marking scan %s: %v", scanId, r)
		}
	}()

	pages, loadErr := s.LoadScan(scanId)
	if loadErr != nil {
		return fmt.Errorf("error loading scan %s: %w", scanId, loadErr)
	}
	sc := scan{id: scanId, pages: pages}
	defer sc.close()

	if len(pages) != len(template.Pages) {
		return fmt.Errorf(
			"page count %d for scan %s does not match page count %d of template",
			len(pages), scanId, len(template.Pages),
		)
	}

	marks, markErr := marker.Evaluate(sc.pages, template)
	if markErr != nil {
		return fmt.Errorf("scan %s failed marking: %w", scanId, markErr)
	}
	sc.close()

	out.ScanId = scanId
	out.Marks = make([]dto.Mark, len(marks.Answers))
	for i, a := range marks.Answers {
		out.Marks[i] = *dto.AdaptMark(&a)
	}
	return nil
}
