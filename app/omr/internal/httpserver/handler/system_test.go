package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

func newTestResources(t *testing.T) ServerResources {
	t.Helper()

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}

	return s
}

func TestParseLimit(t *testing.T) {
	tests := []struct {
		name       string
		query      string
		wantLimit  int
		wantStatus int
	}{
		{
			name:       "default",
			query:      "",
			wantLimit:  defaultLimit,
			wantStatus: http.StatusOK,
		},
		{
			name:       "valid",
			query:      "?limit=10",
			wantLimit:  10,
			wantStatus: http.StatusOK,
		},
		{
			name:       "zero",
			query:      "?limit=0",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "negative",
			query:      "?limit=-1",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "not integer",
			query:      "?limit=abc",
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/test"+tt.query, nil)
			rr := httptest.NewRecorder()

			got, ok := parseLimit(rr, req)

			if rr.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d", rr.Code, tt.wantStatus)
			}

			if tt.wantStatus == http.StatusOK && (!ok || got != tt.wantLimit) {
				t.Fatalf("limit = %d, ok = %v, want %d, true", got, ok, tt.wantLimit)
			}
		})
	}
}

func TestGetResourceUtilization(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	req := httptest.NewRequest(http.MethodGet, "/system/utilization?limit=5", nil)
	rr := httptest.NewRecorder()

	GetResourceUtilization(s)(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d", rr.Code)
	}

	var result ResourceUtilization
	if err := json.Unmarshal(rr.Body.Bytes(), &result); err != nil {
		t.Fatal("invalid JSON:", err)
	}

	if len(result.CpuHistory) > 5 {
		t.Fatal("cpu history exceeds limit")
	}

	if len(result.MemoryHistory) > 5 {
		t.Fatal("memory history exceeds limit")
	}
}

func TestGetResourceUtilizationInvalidLimit(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	req := httptest.NewRequest(http.MethodGet, "/system/utilization?limit=-5", nil)
	rr := httptest.NewRecorder()

	GetResourceUtilization(s)(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rr.Code)
	}
}

func TestGetLogs(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	req := httptest.NewRequest(http.MethodGet, "/system/logs?limit=5", nil)
	rr := httptest.NewRecorder()

	GetLogs(s)(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d", rr.Code)
	}

	if ct := rr.Header().Get("Content-Type"); !strings.Contains(ct, "text/plain") {
		t.Fatalf("content type = %q", ct)
	}
}

func TestGetCpuInfo(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	req := httptest.NewRequest(http.MethodGet, "/system/cpu?limit=5", nil)
	rr := httptest.NewRecorder()

	GetCpuInfo(s)(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d", rr.Code)
	}

	var result DetailedCpuInfo
	if err := json.Unmarshal(rr.Body.Bytes(), &result); err != nil {
		t.Fatal("invalid JSON:", err)
	}
}

func TestGetMemoryInfo(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	req := httptest.NewRequest(http.MethodGet, "/system/memory?limit=5", nil)
	rr := httptest.NewRecorder()

	GetMemoryInfo(s)(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d", rr.Code)
	}

	var result DetailedMemoryInfo
	if err := json.Unmarshal(rr.Body.Bytes(), &result); err != nil {
		t.Fatal("invalid JSON:", err)
	}
}

func TestCheckAdminKey(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	s.SetAdminKey("secret")

	t.Run("valid", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("OMR-Admin-Key", "secret")

		rr := httptest.NewRecorder()

		CheckAdminKey(s)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("status = %d", rr.Code)
		}
	})

	t.Run("invalid", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("OMR-Admin-Key", "wrong")

		rr := httptest.NewRecorder()

		CheckAdminKey(s)(rr, req)

		if rr.Code != http.StatusUnauthorized {
			t.Fatalf("status = %d", rr.Code)
		}
	})
}

func TestResourceLimitQueryIsStable(t *testing.T) {
	s := newTestResources(t)
	defer s.Close()

	for _, limit := range []int{1, 5, 30} {
		req := httptest.NewRequest(
			http.MethodGet,
			"/system/utilization?limit="+strconv.Itoa(limit),
			nil,
		)

		rr := httptest.NewRecorder()

		GetResourceUtilization(s)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("limit %d: status = %d", limit, rr.Code)
		}
	}
}
