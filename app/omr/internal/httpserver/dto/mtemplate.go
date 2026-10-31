/*
This package implements the Data Transfer Objects. That is, the structured data
we expect to send to/from the client. For each of these types, we include
functions for serialization, deserialization, and validation where appropriate.
*/
package dto

import (
	"encoding/json"
	"fmt"
	"strings"
	"ubco-team15/omr/internal/marker"
)

// Parses and validates a marking template from JSON text.
func ParseMarkingTemplate(jsonBuf []byte) (*MarkingTemplate, error) {
	v := &MarkingTemplate{}
	if err := json.Unmarshal(jsonBuf, v); err != nil {
		return nil, err
	}
	if err := v.validate(); err != nil {
		return nil, err
	}
	return v, nil
}

type MarkingTemplate struct {
	Config MarkingConfig `json:"config"`
	Pages  []MarkingPage `json:"pages"`
}

type MarkingConfig struct {
	FillThreshold float64 `json:"fillThreshold"`
	// SelectionThreshold, when set, is used in place of FillThreshold for
	// the final gap-based selection cutoff only; see
	// marker.Config.SelectionThreshold for why that needs to be a separate
	// knob from FillThreshold's other (alignment-fallback) role. This one
	// must stay a pointer, unlike FillThreshold/FlagThreshold above: unset
	// has to mean "fall back to FillThreshold", not silently become 0,
	// which would disable gap-based selection for any question that
	// doesn't set it.
	SelectionThreshold *float64 `json:"selectionThreshold,omitempty"`
	BubbleInset        float64  `json:"bubbleInset"`
	FlagThreshold      float64  `json:"flagThreshold"`
	SearchRadius       int      `json:"searchRadius"`
	// SearchGroupSize/GroupSearchRadius split a wide row into
	// independently-aligned groups instead of one shared-offset search for
	// the whole row; see marker.Config.SearchGroupSize for the full
	// rationale. Both 0 (default) keeps SearchRadius's original behavior.
	SearchGroupSize   int `json:"searchGroupSize"`
	GroupSearchRadius int `json:"groupSearchRadius"`
}

type MarkingPage struct {
	Questions []Question `json:"questions"`
}

type Question struct {
	ID           string           `json:"id"`
	BubbleWidth  int              `json:"bubbleWidth"`
	BubbleHeight int              `json:"bubbleHeight"`
	Type         string           `json:"type,omitempty"`
	Options      []QuestionOption `json:"options"`
}

type QuestionOption struct {
	Label string `json:"label"`
	X     int    `json:"x"`
	Y     int    `json:"y"`
	// BaselineBias corrects for this option's own printed glyph reading a
	// different natural (unmarked) ink level than its question's other
	// options; see marker.Bubble.BaselineBias for the full rationale. 0
	// (default) leaves detection exactly as before.
	BaselineBias float64 `json:"baselineBias"`
}

//
// Validators.
//

func (t *MarkingTemplate) validate() error {
	if err := t.Config.validate(); err != nil {
		return fmt.Errorf("config: %w", err)
	}

	if len(t.Pages) == 0 {
		return fmt.Errorf("pages must contain at least one page")
	}

	questionIDs := make(map[string]struct{})

	for i, page := range t.Pages {
		if err := page.validate(questionIDs); err != nil {
			return fmt.Errorf("pages[%d]: %w", i, err)
		}
	}

	return nil
}

func (c *MarkingConfig) validate() error {
	if c.FillThreshold < 0 || c.FillThreshold > 1 {
		return fmt.Errorf("fillThreshold must be between 0 and 1")
	}

	if c.SelectionThreshold != nil && (*c.SelectionThreshold < 0 || *c.SelectionThreshold > 1) {
		return fmt.Errorf("selectionThreshold must be between 0 and 1")
	}

	if c.BubbleInset < 0 || c.BubbleInset > 1 {
		return fmt.Errorf("bubbleInset must be between 0 and 1")
	}

	if c.FlagThreshold < 0 || c.FlagThreshold > 1 {
		return fmt.Errorf("flagThreshold must be between 0 and 1")
	}

	if c.SearchRadius < 0 {
		return fmt.Errorf("searchRadius must be nonnegative")
	}

	if c.SearchGroupSize < 0 {
		return fmt.Errorf("searchGroupSize must be nonnegative")
	}

	if c.GroupSearchRadius < 0 {
		return fmt.Errorf("groupSearchRadius must be nonnegative")
	}

	return nil
}

func (p *MarkingPage) validate(ids map[string]struct{}) error {
	if len(p.Questions) == 0 {
		return fmt.Errorf("questions must contain at least one question")
	}

	for i, q := range p.Questions {
		if _, exists := ids[q.ID]; exists {
			return fmt.Errorf("duplicate question id %q", q.ID)
		}

		ids[q.ID] = struct{}{}

		if err := q.validate(); err != nil {
			return fmt.Errorf("questions[%d]: %w", i, err)
		}
	}

	return nil
}

func (q *Question) validate() error {

	switch {
	case q.BubbleWidth <= 0:
		return fmt.Errorf("bubbleWidth must be positive")
	case q.BubbleHeight <= 0:
		return fmt.Errorf("bubbleHeight must be positive")
	case q.Type != "" && q.Type != "single" && q.Type != "multi":
		return fmt.Errorf(
			"type must be \"multi\", \"single\", " +
				"or omitted (defaults to \"single\")",
		)
	case len(q.Options) == 0:
		return fmt.Errorf("question must contain at least one option")
	}

	labels := make(map[string]struct{})

	for i, option := range q.Options {
		if _, exists := labels[option.Label]; exists {
			return fmt.Errorf("duplicate option label %q", option.Label)
		}

		labels[option.Label] = struct{}{}

		if err := option.validate(); err != nil {
			return fmt.Errorf("options[%d]: %w", i, err)
		}
	}

	return nil
}

func (o *QuestionOption) validate() error {
	if strings.TrimSpace(o.Label) == "" {
		return fmt.Errorf("label cannot be empty")
	}

	if o.X < 0 {
		return fmt.Errorf("x must be non-negative")
	}

	if o.Y < 0 {
		return fmt.Errorf("y must be non-negative")
	}

	return nil
}

//
// Adaptors.
//

// Converts a MarkingTemplate into a marker template (i.e., one that the marker
// package can use).
func AdaptMarkerTemplate(tmpl *MarkingTemplate) *marker.Template {

	template := marker.Template{
		Config: marker.Config{
			FillThreshold:      &tmpl.Config.FillThreshold,
			SelectionThreshold: tmpl.Config.SelectionThreshold,
			BubbleInset:        &tmpl.Config.BubbleInset,
			FlagThreshold:      &tmpl.Config.FlagThreshold,
			SearchRadius:       &tmpl.Config.SearchRadius,
			SearchGroupSize:    &tmpl.Config.SearchGroupSize,
			GroupSearchRadius:  &tmpl.Config.GroupSearchRadius,
		},
		Pages: make([]marker.Page, len(tmpl.Pages)),
	}

	for i, p := range tmpl.Pages {

		template.Pages[i].Questions = make(
			[]marker.Question,
			len(p.Questions),
		)
		for j, q := range p.Questions {

			template.Pages[i].Questions[j].ID = q.ID
			template.Pages[i].Questions[j].Type = q.Type
			template.Pages[i].Questions[j].BubbleWidth = q.BubbleWidth
			template.Pages[i].Questions[j].BubbleHeight = q.BubbleHeight
			template.Pages[i].Questions[j].Options = make(
				[]marker.Bubble, len(q.Options),
			)

			for k, o := range q.Options {
				template.Pages[i].Questions[j].Options[k].Label = o.Label
				template.Pages[i].Questions[j].Options[k].X = o.X
				template.Pages[i].Questions[j].Options[k].Y = o.Y
				template.Pages[i].Questions[j].Options[k].BaselineBias = o.BaselineBias
			}

		}
	}

	return &template

}
