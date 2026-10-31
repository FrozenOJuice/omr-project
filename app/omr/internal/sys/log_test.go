package sys

import (
	"bytes"
	"strings"
	"testing"
)

func TestDumpLogsEmpty(t *testing.T) {
	logCache.Flush()
	var buf bytes.Buffer

	DumpLogs(&buf, 10)

	if got := buf.String(); got != "" {
		t.Fatalf("expected no output, got %q", got)
	}
}

func TestLogAppearsInDump(t *testing.T) {
	logCache.Flush()
	var buf bytes.Buffer

	Log("hello world")
	DumpLogs(&buf, 1)

	got := buf.String()

	if !strings.Contains(got, "hello world") {
		t.Fatalf("expected output to contain log message, got %q", got)
	}
}

func TestDumpLogsLimit(t *testing.T) {
	logCache.Flush()
	Log("first")
	Info("second")
	Warn("third")

	var buf bytes.Buffer
	DumpLogs(&buf, 2)

	out := buf.String()

	if strings.Contains(out, "first") {
		t.Fatal("oldest log should not have been included")
	}

	if !strings.Contains(out, "second") {
		t.Fatal("expected second log")
	}

	if !strings.Contains(out, "third") {
		t.Fatal("expected third log")
	}
}

func TestDumpLogsZero(t *testing.T) {
	logCache.Flush()
	Error("hello")

	var buf bytes.Buffer
	DumpLogs(&buf, 0)

	if buf.Len() != 0 {
		t.Fatalf("expected no output, got %q", buf.String())
	}
}

func TestDumpLogsNegative(t *testing.T) {
	logCache.Flush()
	Debug("hello")

	var buf bytes.Buffer
	DumpLogs(&buf, -1)

	if buf.Len() != 0 {
		t.Fatalf("expected no output, got %q", buf.String())
	}
}
