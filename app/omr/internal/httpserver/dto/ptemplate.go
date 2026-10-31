package dto

import (
	"encoding/json"
	"fmt"
	"image"
	"ubco-team15/omr/internal/scanner"

	"gocv.io/x/gocv"
)

//
// General helper functions
//

func inBounds(width, height, x, y int) error {
	switch {
	case x < 0:
		return fmt.Errorf("x-coordinates must be nonnegative")
	case y < 0:
		return fmt.Errorf("y-coordinates must be nonnegative")
	case x > width:
		return fmt.Errorf("x-coordinates must be less than the width")
	case y > height:
		return fmt.Errorf("y-coordinates must be less than the height")
	}
	return nil
}

//
// Validator
//

// Parses and validates a preprocessing template from JSON text.
func ParsePreprocessingTemplate(
	jsonBuf []byte,
) (*PreprocessingTemplate, error) {
	v := &PreprocessingTemplate{}
	if err := json.Unmarshal(jsonBuf, v); err != nil {
		return nil, err
	}
	if err := v.validate(); err != nil {
		return nil, err
	}
	return v, nil
}

type PreprocessingTemplate struct {
	Width  int `json:"width"`
	Height int `json:"height"`
	// NativeDpi is the DPI this template's anchor/binarization tuning is
	// calibrated against, so /scan/pdf can request a matching-resolution
	// render by default instead of falling back to a fixed constant. Zero
	// means unknown (templates authored before this field existed).
	NativeDpi float64 `json:"nativeDpi"`
	Config    struct {
		BlurSize            int     `json:"blurSize"`
		MorphCloseSize      int     `json:"morphCloseSize"`
		MinAnchorConfidence float64 `json:"minAnchorConfidence"`
		AdaptiveBlockSize   int     `json:"adaptiveBlockSize"`
		AdaptiveC           float64 `json:"adaptiveC"`
		// ReferenceRatio is the imgSize/templateSize ratio (see
		// scanner.sizeRatio) that BlurSize/AdaptiveBlockSize/
		// MorphCloseSize above were tuned against. Zero means unknown, in
		// which case those values are used unscaled regardless of the
		// actual scan's resolution.
		ReferenceRatio float64 `json:"referenceRatio"`
	} `json:"config"`
	Pages []struct {
		Anchors []struct {
			Center struct {
				X int `json:"x"`
				Y int `json:"y"`
			} `json:"center"`
			Roi struct {
				Min struct {
					X int `json:"x"`
					Y int `json:"y"`
				} `json:"min"`
				Max struct {
					X int `json:"x"`
					Y int `json:"y"`
				} `json:"max"`
			} `json:"roi"`
		} `json:"anchors"`
	} `json:"pages"`
}

func (p *PreprocessingTemplate) validate() error {
	switch {
	case p.Width <= 0:
		return fmt.Errorf("width must be positive")
	case p.Height <= 0:
		return fmt.Errorf("height must be positive")
	case p.NativeDpi < 0:
		return fmt.Errorf("nativeDpi must be nonnegative")
	case p.Config.ReferenceRatio < 0:
		return fmt.Errorf("referenceRatio must be nonnegative")
	case p.Config.BlurSize <= 0:
		return fmt.Errorf("blurSize must be nonnegative")
	case p.Config.BlurSize%2 == 0:
		return fmt.Errorf("blurSize must be odd")
	case p.Config.MorphCloseSize < 0:
		return fmt.Errorf("morphCloseSize must be nonnegative")
	case p.Config.MinAnchorConfidence <= 0.0,
		p.Config.MinAnchorConfidence >= 1.0:
		return fmt.Errorf("minAnchorConfidence must be in (0.0, 1.0)")
	case len(p.Pages) == 0:
		return fmt.Errorf("at least one page must be included")
	case p.Config.AdaptiveBlockSize == 0:
		return fmt.Errorf("adaptiveBlockSize is required")
	case p.Config.AdaptiveBlockSize%2 == 0:
		return fmt.Errorf("adaptiveBlockSize must be odd")
	case p.Config.AdaptiveBlockSize <= 0:
		return fmt.Errorf("adaptiveBlockSize must be positive")
	}

	const minAnchors = 3
	for _, page := range p.Pages {
		if len(page.Anchors) < minAnchors {
			return fmt.Errorf(
				"each page must have at least %d anchors",
				minAnchors,
			)
		}
		for _, anchor := range page.Anchors {
			err := inBounds(p.Width, p.Height, anchor.Center.X, anchor.Center.Y)
			if err != nil {
				return err
			}
			err = inBounds(
				p.Width, p.Height,
				anchor.Roi.Min.X, anchor.Roi.Min.Y,
			)
			if err != nil {
				return err
			}
			err = inBounds(
				p.Width, p.Height,
				anchor.Roi.Max.X, anchor.Roi.Max.Y,
			)
			if err != nil {
				return err
			}
		}
	}

	return nil
}

//
// Adaptors
//

// Converts a PreprocessingTemplate into a scanner Template, populating it with
// the given anchors. An error will be returned if the number of anchors does
// not match the number of anchors expected by the template.
func AdaptScannerTemplate(
	tmpl *PreprocessingTemplate,
	anchors [][]*gocv.Mat,
) (*scanner.Template, error) {

	nPages := len(tmpl.Pages)
	if len(anchors) != nPages {
		return nil, fmt.Errorf(
			"preprocessing template page count (%d) doesn't match anchors "+
				"given (%d)",
			nPages, len(anchors),
		)
	}

	for i := range nPages {
		if len(tmpl.Pages[i].Anchors) != len(anchors[i]) {
			return nil, fmt.Errorf(
				"preprocessing template anchor count for page %d (%d) "+
					"doesn't match anchors given (%d)",
				i, len(tmpl.Pages[i].Anchors), len(anchors[i]),
			)
		}
	}

	scannerTmpl := scanner.Template{
		Width:     tmpl.Width,
		Height:    tmpl.Height,
		NativeDpi: tmpl.NativeDpi,
		Config: scanner.Config{
			BlurSize:            tmpl.Config.BlurSize,
			MorphCloseSize:      tmpl.Config.MorphCloseSize,
			MinAnchorConfidence: float32(tmpl.Config.MinAnchorConfidence),
			AdaptiveBlockSize:   tmpl.Config.AdaptiveBlockSize,
			AdaptiveC:           float32(tmpl.Config.AdaptiveC),
			ReferenceRatio:      tmpl.Config.ReferenceRatio,
		},
		Pages: make([]scanner.ScanPage, nPages),
	}

	for pageIdx := range nPages {
		nAnchors := len(tmpl.Pages[pageIdx].Anchors)
		scannerTmpl.Pages[pageIdx].Anchors = make(
			[]scanner.Anchor,
			nAnchors,
		)
		for anchorIdx := range nAnchors {
			scannerTmpl.Pages[pageIdx].Anchors[anchorIdx] = scanner.Anchor{
				Image: anchors[pageIdx][anchorIdx],
				ROI: image.Rectangle{
					Min: image.Point{
						X: tmpl.Pages[pageIdx].Anchors[anchorIdx].Roi.Min.X,
						Y: tmpl.Pages[pageIdx].Anchors[anchorIdx].Roi.Min.Y,
					},
					Max: image.Point{
						X: tmpl.Pages[pageIdx].Anchors[anchorIdx].Roi.Max.X,
						Y: tmpl.Pages[pageIdx].Anchors[anchorIdx].Roi.Max.Y,
					},
				},
				Center: image.Point{
					X: tmpl.Pages[pageIdx].Anchors[anchorIdx].Center.X,
					Y: tmpl.Pages[pageIdx].Anchors[anchorIdx].Center.Y,
				},
			}
		}
	}

	return &scannerTmpl, nil
}
