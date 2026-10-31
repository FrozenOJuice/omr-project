package dto

import "encoding/json"

//
// Scan Results (Outgoing)
//

type ScanError struct {
	// The starting page (1-based) of the PDF where the error occurred.
	From uint `json:"from"`
	// The ending page (1-based; inclusive) of the PDF where the error
	// occurred.
	Thru uint `json:"thru"`
	// The error message. This is meant for debugging, not for end-users.
	Debug string `json:"debug"`
}

type ScanResult struct {
	ScanIds []string    `json:"scanIds"`
	Errors  []ScanError `json:"errors"`
}

// Makes a new ScanResult struct. All zero-values from the given slices will
// be omitted.
func NewScanResult(scanIds []string, errors []*ScanError) ScanResult {

	ids := make([]string, 0, len(scanIds))
	errs := make([]ScanError, 0, len(errors))

	for _, scanId := range scanIds {
		if scanId != "" {
			ids = append(ids, scanId)
		}
	}
	for _, err := range errors {
		if err != nil {
			errs = append(errs, *err)
		}
	}

	return ScanResult{
		ScanIds: ids,
		Errors:  errs,
	}

}

//
// Scan Deletion Request (incoming)
//

type ScanDeleteRequest []string

func ParseScanDeleteRequest(jsonBuf []byte) (*ScanDeleteRequest, error) {
	v := &ScanDeleteRequest{}
	if err := json.Unmarshal(jsonBuf, v); err != nil {
		return nil, err
	}
	return v, nil
}
