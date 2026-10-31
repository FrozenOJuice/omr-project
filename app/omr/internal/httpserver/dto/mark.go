package dto

import (
	"encoding/json"
	"fmt"
	"ubco-team15/omr/internal/marker"
)

//
// MarkingJobRequest (Incoming)
//

// Parses and validates a marking job request from JSON text.
func ParseMarkingJobRequest(jsonBuf []byte) (*MarkingJobRequest, error) {
	v := &MarkingJobRequest{}
	if err := json.Unmarshal(jsonBuf, v); err != nil {
		return nil, err
	}
	if err := v.validate(); err != nil {
		return nil, err
	}
	return v, nil
}

type MarkingJobRequest struct {
	TemplateId string   `json:"template"`
	ScanIds    []string `json:"scans"`
}

func (m *MarkingJobRequest) validate() error {

	switch {
	case m.TemplateId == "":
		return fmt.Errorf("template field must be provided")
	case m.ScanIds == nil:
		return fmt.Errorf("scans must be provided")
	case len(m.ScanIds) == 0:
		return fmt.Errorf("scans must not be empty")
	}

	return nil
}

//
// MarkingResult (Outgoing)
//

type MarkingResult struct {
	PagesMarked int            `json:"pagesMarked"`
	TemplateId  string         `json:"templateId"`
	Scans       []Scan         `json:"scans"`
	Errors      []MarkingError `json:"errors"`
}

// MarkingError describes why a single scan in a marking job's batch failed:
// a missing scan, a page count mismatch against the template, or a marking
// failure. It doesn't abort the rest of the batch; see NewMarkingResult.
type MarkingError struct {
	// The scanId (as given in the request) that failed marking.
	ScanId string `json:"scanId"`
	// The error message. This is meant for debugging, not for end-users.
	Debug string `json:"debug"`
}

// Builds a MarkingResult from a batch of per-scan attempts. scans and errs
// must be the same length and index-aligned: for index i, exactly one of
// scans[i] (a successfully marked scan) or errs[i] (why it failed) is the
// zero/nil value. Mirrors NewScanResult's shape for POST /scan/pdf.
func NewMarkingResult(
	templateId string,
	pagesPerScan int,
	scans []Scan,
	errs []*MarkingError,
) MarkingResult {
	successfulScans := make([]Scan, 0, len(scans))
	errors := make([]MarkingError, 0, len(errs))

	for i := range scans {
		if errs[i] != nil {
			errors = append(errors, *errs[i])
			continue
		}
		successfulScans = append(successfulScans, scans[i])
	}

	return MarkingResult{
		PagesMarked: len(successfulScans) * pagesPerScan,
		TemplateId:  templateId,
		Scans:       successfulScans,
		Errors:      errors,
	}
}

type Scan struct {
	ScanId string `json:"scanId"`
	Marks  []Mark `json:"marks"`
}

type Mark struct {
	QuestionId string   `json:"questionId"`
	Flagged    bool     `json:"flagged"`
	Selected   []string `json:"selected"`
	Confidence float64  `json:"confidence"`
	// PageIndex is the 0-based page (matching the scan's page images) the
	// question's bubbles were found on. See marker.Answer.
	PageIndex int            `json:"pageIndex"`
	Bounds    QuestionBounds `json:"bounds"`
	Boxes     []Box          `json:"boxes"`
}

// Box is the bounding box of a single option's bubble, selected or not, in
// the page's scan pixel coordinates. See marker.Box.
type Box struct {
	Label    string `json:"label"`
	Selected bool   `json:"selected"`
	X        int    `json:"x"`
	Y        int    `json:"y"`
	Width    int    `json:"width"`
	Height   int    `json:"height"`
}

// QuestionBounds is the bounding box enclosing every one of a question's
// bubbles, not just the selected ones. See marker.QuestionBounds.
type QuestionBounds struct {
	X      int `json:"x"`
	Y      int `json:"y"`
	Width  int `json:"width"`
	Height int `json:"height"`
}

//
// Adaptors.
//

// Convert the output from the marker package into Mark DTO structs.
func AdaptMark(a *marker.Answer) *Mark {

	mark := Mark{}

	mark.Flagged = a.Flag
	mark.QuestionId = a.QuestionID
	mark.Selected = a.Selected
	if mark.Selected == nil {
		mark.Selected = make([]string, 0)
	}
	mark.Confidence = a.Confidence
	mark.PageIndex = a.PageIndex
	mark.Bounds = QuestionBounds{
		X:      a.Bounds.X,
		Y:      a.Bounds.Y,
		Width:  a.Bounds.Width,
		Height: a.Bounds.Height,
	}
	mark.Boxes = make([]Box, len(a.Boxes))
	for j, box := range a.Boxes {
		mark.Boxes[j] = Box{
			Label:    box.Label,
			Selected: box.Selected,
			X:        box.X,
			Y:        box.Y,
			Width:    box.Width,
			Height:   box.Height,
		}
	}

	return &mark

}
