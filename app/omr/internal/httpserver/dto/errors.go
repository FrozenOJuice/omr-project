package dto

import (
	"compress/flate"
	"compress/gzip"
	"encoding/json"
	"net/http"
	"strings"
)

type ErrReason string

const (
	ErrInvalidRequest    ErrReason = "invalid_request"
	ErrTemplateNotFound  ErrReason = "template_not_found"
	ErrScanNotFound      ErrReason = "scan_not_found"
	ErrPageCountMismatch ErrReason = "page_count_mismatch"
	ErrLowScanQuality    ErrReason = "low_scan_quality"
	ErrPageOutOfOrder    ErrReason = "page_out_of_order"
	ErrInternal          ErrReason = "internal_error"
	ErrMissingAnchor     ErrReason = "missing_anchor"
	ErrMalformedPdf      ErrReason = "malformed_pdf"
	ErrContentTooLarge   ErrReason = "content_too_large"
	ErrMarkingFailed     ErrReason = "marking_failed"
)

// Sends a JSON error response with a classifier (reason) so that the client
// can distinguish between different types of errors.
func SendError(
	w http.ResponseWriter,
	status int,
	reason ErrReason,
	message string,
) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	resp := map[string]string{
		// I'd like to change this to "reason" in the future.
		"code":    string(reason),
		"message": message,
	}
	if err := enc.Encode(resp); err != nil {
		panic(err)
	}
}

// Sends a JSON body.
func SendJson(w http.ResponseWriter, v any) {
	w.Header().Add("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		http.Error(w, "error writing response", http.StatusInternalServerError)
	}
}

// If the request header indicates that it can handle compressed data in one of
// the recognized formats, then we will send the given data as JSON in that
// format. Otherwise, the uncompressed JSON will be sent.
//
// At the time of writing, supported formats include gzip and deflate.
func SendCompressedJson(w http.ResponseWriter, r *http.Request, v any) error {
	w.Header().Add("Content-Type", "application/json")

	switch {
	case strings.Contains(r.Header.Get("Accept-Encoding"), "deflate"):
		w.Header().Add("Content-Encoding", "deflate")

		compressor, _ := flate.NewWriter(w, 1)
		defer compressor.Close()

		encoder := json.NewEncoder(compressor)
		return encoder.Encode(v)

	case strings.Contains(r.Header.Get("Accept-Encoding"), "gzip"):
		w.Header().Add("Content-Encoding", "gzip")

		compressor := gzip.NewWriter(w)
		defer compressor.Close()

		encoder := json.NewEncoder(compressor)
		return encoder.Encode(v)

	default:
		encoder := json.NewEncoder(w)
		return encoder.Encode(v)
	}
}
