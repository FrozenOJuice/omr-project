package scanner

import (
	"errors"
	"fmt"
	"sync"

	"gocv.io/x/gocv"
	"golang.org/x/sync/errgroup"
)

//
// This file contains functions used for scanning matrices directly rather
// than scanning images.
//

// Contains the preprocessed and ordered pages of a single scanned exam. Use
// the Close method to close all nested matrices when you're done.
type ExamData struct {
	Pages []*ScanData
}

// Closes each page's matrices for this exam.
func (e *ExamData) Close() {
	for i := range e.Pages {
		if e.Pages[i] != nil {
			e.Pages[i].Binary.Close()
			e.Pages[i].Picture.Close()
		}
	}
	e.Pages = nil
}

// Accepts an arbitrary number of scanned pages (as grayscale OpenCV matrices)
// and preprocesses them. The number of scanned pages must be divisible by the
// number of pages in the preprocessing template.
//
// In the case that one or more pages are out of order--i.e., if the template
// expects two pages per exam but the given matrices are ordered such that the
// second page appears before the first--then this function will silently
// attempt to resolve the issue and will shuffle the output to have the correct
// ordering. Even though this issue is recoverable, it should be noted that
// many out-of-order pages can dramatically increase the time it takes to
// preprocess the pages.
//
// The returned matrices are not linked to the originals. That means that you
// can safely close the original pages after this operation.
func ScanMats(pages []*gocv.Mat, tmpl *Template) ([]ExamData, error) {

	nPagesPerExam := len(tmpl.Pages)
	nPages := len(pages)
	nExams := nPages / nPagesPerExam

	if nPages%nPagesPerExam != 0 {
		return nil, fmt.Errorf(
			"given %d pages, which is incompatible with a template "+
				"expecting %d pages",
			nPages, nPagesPerExam,
		)
	}

	for i := range pages {
		if pages[i] == nil {
			return nil, fmt.Errorf(
				"ScanMats cannot operate on nil matrices (page %d is nil)",
				i,
			)
		}
	}

	results := make([]ExamData, nExams)

	wg := errgroup.Group{}
	for i := range nExams {
		wg.Go(func() (err error) {
			defer func() {
				if r := recover(); r != nil {
					err = fmt.Errorf("exam %d: panic: %v", i, r)
				}
			}()

			exam, err := ScanExamMats(
				pages[(i*nPagesPerExam):((i+1)*nPagesPerExam)],
				tmpl,
			)
			if err != nil {
				return err
			}
			results[i] = exam

			return nil
		})
	}
	if err := wg.Wait(); err != nil {
		for i := range results {
			results[i].Close()
		}
		return nil, err
	}

	return results, nil
}

// Preprocesses an exam's pages. If any page is out of order this function
// will attempt to resolve the issue by shuffling the order around. In any
// case, the returned exam will have its pages in the correct order to match
// the template.
//
// Importantly, the exams in the returned ExamData are independent of the
// matrices passed to it. That means that one can be closed without closing the
// other.
func ScanExamMats(
	pages []*gocv.Mat,
	tmpl *Template,
) (ExamData, error) {

	n := len(pages)
	if n != len(tmpl.Pages) {
		return ExamData{}, fmt.Errorf("ScanExamMats: page count mismatch")
	}
	for i := range pages {
		if pages[i] == nil {
			return ExamData{}, fmt.Errorf("ScanExamMats: nil matrix received")
		}
	}

	result := ExamData{
		Pages: make([]*ScanData, n),
	}
	mutexes := make([]sync.Mutex, n)

	wg := errgroup.Group{}
	for i, page := range pages {
		wg.Go(func() (err error) {
			defer func() {
				if r := recover(); r != nil {
					err = fmt.Errorf("exam page %d: panic: %v", i, r)
				}
			}()

			//
			// Iterate over the possible page indices, starting with the order
			// that the matrices are given.
			//

			for j := range n {
				idx := (i + j) % n

				scan, err := scanPageMat(page, tmpl, idx)
				if err != nil {
					continue
				}

				mutexes[idx].Lock()
				if result.Pages[idx] != nil {
					mutexes[idx].Unlock()
					scan.Close()
					return errors.New("duplicate pages in an exam")
				}
				result.Pages[idx] = scan
				mutexes[idx].Unlock()
				return nil
			}

			return fmt.Errorf("unrecognizable page %d", i)
		})
	}
	if err := wg.Wait(); err != nil {
		result.Close()
		return ExamData{}, err
	}

	return result, nil
}

// Preprocesses a single page as a grayscale OpenCV matrix.
func scanPageMat(
	page *gocv.Mat,
	tmpl *Template,
	pageIdx int,
) (*ScanData, error) {

	data, err := preprocessPage(page.Clone(), tmpl, pageIdx)
	if err != nil {
		var qerr *QualityError
		if !errors.As(err, &qerr) {
			return nil, err
		}
		data.Close()
		return nil, fmt.Errorf("preprocessing pipeline failed: %w", err)
	}

	return data, nil
}
