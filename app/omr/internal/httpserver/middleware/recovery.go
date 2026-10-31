package middleware

import (
	"fmt"
	"io"
	"net/http"
	"runtime"
	"strings"
	"sync"
	"time"
	"ubco-team15/omr/internal/sys"

	"os"
)

const logFilePath = "debug.log"

var logFileMu sync.Mutex
var logFile io.WriteCloser

// Makes it so that handlers will gracefully recover from panics and send back
// an error message.
func Recovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		defer RecoverAndRespond(w, r)
		next.ServeHTTP(w, r)
	})
}

func formatDate(t time.Time) string {
	return t.Format("2006-01-02 15:04:05.000")
}

// Invokes [recover] and, if there was a panic recovered, sends back a 500
// response and logs the panic.
func RecoverAndRespond(w http.ResponseWriter, r *http.Request) {
	if err := recover(); err != nil {
		sys.Error(
			"panic recovered",
			"endpoint", r.Method+" "+r.URL.Path,
			"log file", logFilePath,
			"err", err,
		)

		logFileMu.Lock()
		defer logFileMu.Unlock()

		if logFile == nil {
			f, err := os.Create(logFilePath)
			if err != nil {
				panic("failed to create debug.log file")
			}
			logFile = f
		}

		const maxStackTraceLen = 4 << 20 // 4 KB
		buf := make([]byte, maxStackTraceLen)
		nBytes := runtime.Stack(buf, false)

		trace := string(buf[:nBytes])
		trace = strings.Join(strings.Split(trace, "\n"), "\n│  ")
		trace = "│  " + trace
		buf = []byte(trace)

		fmt.Fprint(
			logFile,
			"\n┌── Panic Log ────────────────────────────────────────────────────────────────────────────────────────────────\n│\n",
		)

		fmt.Fprintf(
			logFile,
			"│   endpoint..... %s\n"+
				"│   time......... %s\n"+
				"│   recovered.... %v\n│\n",
			r.Method+" "+r.URL.Path,
			formatDate(time.Now()),
			err,
		)

		logFile.Write(buf)
		if nBytes == maxStackTraceLen {
			fmt.Fprint(logFile, "\n│  [...]\n│")
		}

		fmt.Fprint(
			logFile,
			"\n└─────────────────────────────────────────────────────────────────────────────────────────────────────────────\n",
		)

		// Only write a response if one hasn't already been written.
		if w.Header().Get("Content-Type") == "" {
			http.Error(
				w,
				"Unknown server error. Check the server logs.",
				http.StatusInternalServerError,
			)
		}
	}
}
