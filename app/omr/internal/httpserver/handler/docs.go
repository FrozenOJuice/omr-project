/*
This package contains handler functions for the HTTP server.
*/
package handler

import (
	"net/http"
)

// Sends the OpenAPI specification in YAML format.
func OpenAPISpec(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/x-yaml")
	http.ServeFile(w, r, "./api/openapi.yaml")
}

// Writes a 200 response to indicate that the server is functioning.
func Health(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
}
