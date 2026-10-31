package middleware

import (
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestRecovery(t *testing.T) {

	easilyStartled := http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			panic("WHAT WAS THAT?!")
		},
	)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()

	Recovery(easilyStartled).ServeHTTP(rr, req)
	Recovery(easilyStartled).ServeHTTP(rr, req)

	logFile.Close()
	logFile = nil
	os.Remove(logFilePath)

}
