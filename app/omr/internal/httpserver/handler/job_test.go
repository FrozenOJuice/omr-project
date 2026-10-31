package handler

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

//
// Many of the following tests were written by an LLM and they should probably
// be refactored/rewritten at some point.
//

//
// Helpers
//

func newRegistrar(t *testing.T) *JobRegistrar {
	t.Helper()

	r := NewJobRegistrar(time.Hour)
	t.Cleanup(r.Close)
	return r
}

func testJobResult() *JobResult {
	result := NewJobResult()

	result.Status = http.StatusCreated
	result.Headers.Set("Content-Type", "application/json")
	result.Write([]byte(`{"id":"scan1"}`))

	return result
}

//
// Tests
//

func TestJobRegistrarRegister(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("POST", "/scan", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatalf("Register returned error: %v", err)
	}

	if !j.IsRegistered("job1") {
		t.Fatal("job should be registered")
	}

	job, err := j.Get("job1")
	if err != nil {
		t.Fatal(err)
	}

	if job.Id != "job1" {
		t.Errorf("Id = %q, want %q", job.Id, "job1")
	}

	if job.Method != "POST" {
		t.Errorf("Method = %q, want POST", job.Method)
	}

	if job.Path != "/scan" {
		t.Errorf("Path = %q, want /scan", job.Path)
	}

	if job.Started.IsZero() {
		t.Error("Started was not initialized")
	}

	if job.Progress != 0 {
		t.Errorf("Progress = %v, want 0", job.Progress)
	}

	if !job.Finished.IsZero() {
		t.Error("Finished should be zero")
	}

	if job.Success {
		t.Error("Success should default to false")
	}

	if job.Notes != "" {
		t.Errorf("Notes = %q, want empty string", job.Notes)
	}
}

func TestJobRegistrarRegisterConflict(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	err := j.Register("job1", req)
	if err != ErrJobIdConflict {
		t.Fatalf("expected ErrJobIdConflict, got %v", err)
	}
}

func TestJobRegistrarGetSetProgress(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	if err := j.SetProgress("job1", 0.35); err != nil {
		t.Fatal(err)
	}

	job, err := j.Get("job1")
	if err != nil {
		t.Fatal(err)
	}

	if job.Progress != 0.35 {
		t.Errorf("progress = %v, want 0.35", job.Progress)
	}
}

func TestJobRegistrarProgressMissingJob(t *testing.T) {
	j := newRegistrar(t)

	if _, err := j.Get("missing"); err != ErrJobNotFound {
		t.Fatalf("expected ErrJobNotFound, got %v", err)
	}

	if err := j.SetProgress("missing", 0.5); err != ErrJobNotFound {
		t.Fatalf("expected ErrJobNotFound, got %v", err)
	}
}

func TestJobRegistrarWriteNotes(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	if err := j.WriteNotes("job1", "hello world"); err != nil {
		t.Fatal(err)
	}

	job, err := j.Get("job1")
	if err != nil {
		t.Fatal(err)
	}

	if job.Notes != "hello world" {
		t.Errorf("Notes = %q, want %q", job.Notes, "hello world")
	}
}

func TestJobRegistrarWriteNotesMissingJob(t *testing.T) {
	j := newRegistrar(t)

	if err := j.WriteNotes("missing", "notes"); err != ErrJobNotFound {
		t.Fatalf("expected ErrJobNotFound, got %v", err)
	}
}

func TestJobRegistrarFinish(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("POST", "/scan", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	if err := j.SetProgress("job1", 0.25); err != nil {
		t.Fatal(err)
	}

	result := testJobResult()

	if err := j.SetFinished("job1", true, result); err != nil {
		t.Fatal(err)
	}

	job, err := j.Get("job1")
	if err != nil {
		t.Fatal(err)
	}

	if !job.Success {
		t.Error("Success = false, want true")
	}

	if job.Progress != 1.0 {
		t.Errorf("Progress = %v, want 1.0", job.Progress)
	}

	if job.Finished.IsZero() {
		t.Error("Finished was not set")
	}

	gotResult, err := j.GetResult("job1")
	if err != nil {
		t.Fatal(err)
	}

	if gotResult.Status != result.Status {
		t.Errorf("Status = %d, want %d", gotResult.Status, result.Status)
	}

	if gotResult.Body.String() != `{"id":"scan1"}` {
		t.Errorf(
			"Body = %q, want %q",
			gotResult.Body.String(),
			`{"id":"scan1"}`,
		)
	}
}

func TestJobRegistrarFinishMissingJob(t *testing.T) {
	j := newRegistrar(t)

	err := j.SetFinished("missing", true, NewJobResult())
	if err != ErrJobNotFound {
		t.Fatalf("expected ErrJobNotFound, got %v", err)
	}
}

func TestJobRegistrarCannotModifyFinishedJob(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	if err := j.SetFinished("job1", true, NewJobResult()); err != nil {
		t.Fatal(err)
	}

	if err := j.SetProgress("job1", 0.5); err != ErrJobFinished {
		t.Fatalf("expected ErrJobFinished, got %v", err)
	}

	if err := j.SetFinished("job1", false, NewJobResult()); err != ErrJobFinished {
		t.Fatalf("expected ErrJobFinished, got %v", err)
	}
}

func TestJobRegistrarEvictAllOlderThan(t *testing.T) {
	j := newRegistrar(t)

	now := time.Now()

	j.jobs["old"] = &JobDetails{
		Id:      "old",
		Started: now.Add(-2 * time.Hour),
	}

	j.jobs["new"] = &JobDetails{
		Id:      "new",
		Started: now,
	}

	j.jobResults["old"] = &JobResult{
		Status: http.StatusOK,
	}

	j.evictAllOlderThan(time.Hour)

	if j.IsRegistered("old") {
		t.Error("old job should have been evicted")
	}

	if _, ok := j.jobResults["old"]; ok {
		t.Error("old result should have been evicted")
	}

	if !j.IsRegistered("new") {
		t.Error("new job should not have been evicted")
	}
}

func TestJobRegistrarEvictEmpty(t *testing.T) {
	j := newRegistrar(t)

	j.evictAllOlderThan(time.Hour)

	if len(j.jobs) != 0 {
		t.Errorf("len(j.jobs) = %d, want 0", len(j.jobs))
	}
}

func TestJobRegistrarListHandler(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/jobs", nil)

	if err := j.Register("job2", req); err != nil {
		t.Fatal(err)
	}
	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}
	if err := j.Register("job3", req); err != nil {
		t.Fatal(err)
	}

	now := time.Now()

	// Intentionally make the ordering different from insertion order.
	j.jobs["job2"].Started = now.Add(2 * time.Hour)
	j.jobs["job1"].Started = now
	j.jobs["job3"].Started = now.Add(time.Hour)

	rr := httptest.NewRecorder()

	s, err := NewLocalResources(t.TempDir())
	if err != nil {
		t.Fatal("error initializing server resources: " + err.Error())
	}
	defer s.Close()

	j.ListHandler(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusUnauthorized)
	}

	req.Header.Set("OMR-Admin-Key", "admin")
	s.SetAdminKey("admin")

	rr = httptest.NewRecorder()
	j.ListHandler(s).ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusOK)
	}

	var jobs []*JobDetails
	if err := json.Unmarshal(rr.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("error decoding response: %v", err)
	}

	if len(jobs) != 3 {
		t.Fatalf("len(jobs) = %d, want 3", len(jobs))
	}

	if jobs[0].Id != "job1" {
		t.Errorf("jobs[0].Id = %q, want %q", jobs[0].Id, "job1")
	}

	if jobs[1].Id != "job3" {
		t.Errorf("jobs[1].Id = %q, want %q", jobs[1].Id, "job3")
	}

	if jobs[2].Id != "job2" {
		t.Errorf("jobs[2].Id = %q, want %q", jobs[2].Id, "job2")
	}
}

func TestJobRegistrarGetResultMissingJob(t *testing.T) {
	j := newRegistrar(t)

	_, err := j.GetResult("missing")
	if err != ErrJobNotFound {
		t.Fatalf("expected ErrJobNotFound, got %v", err)
	}
}

func TestJobRegistrarGetResult(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	result := testJobResult()

	if err := j.SetFinished("job1", true, result); err != nil {
		t.Fatal(err)
	}

	got, err := j.GetResult("job1")
	if err != nil {
		t.Fatal(err)
	}

	if got.Status != http.StatusCreated {
		t.Errorf("Status = %d, want %d", got.Status, http.StatusCreated)
	}

	if got.Headers["Content-Type"][0] != "application/json" {
		t.Errorf(
			"Content-Type = %q, want application/json",
			got.Headers["Content-Type"],
		)
	}
}

func TestJobRegistrarResultHandler(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	result := testJobResult()

	if err := j.SetFinished("job1", true, result); err != nil {
		t.Fatal(err)
	}

	r := httptest.NewRequest(
		"GET",
		"/result?id=job1",
		nil,
	)

	rr := httptest.NewRecorder()

	j.ResultHandler().ServeHTTP(rr, r)

	if rr.Code != http.StatusCreated {
		t.Fatalf(
			"status = %d, want %d",
			rr.Code,
			http.StatusCreated,
		)
	}

	if rr.Header().Get("Content-Type") != "application/json" {
		t.Errorf(
			"Content-Type = %q, want application/json",
			rr.Header().Get("Content-Type"),
		)
	}

	if rr.Body.String() != result.Body.String() {
		t.Errorf(
			"Body = %q, want %q",
			rr.Body.String(),
			result.Body.String(),
		)
	}
}

func TestJobRegistrarResultHandlerIncomplete(t *testing.T) {
	j := newRegistrar(t)

	req := httptest.NewRequest("GET", "/", nil)

	if err := j.Register("job1", req); err != nil {
		t.Fatal(err)
	}

	r := httptest.NewRequest(
		"GET",
		"/result?id=job1",
		nil,
	)

	rr := httptest.NewRecorder()

	j.ResultHandler().ServeHTTP(rr, r)

	if rr.Code != http.StatusNotFound {
		t.Fatalf(
			"status = %d, want %d",
			rr.Code,
			http.StatusNotFound,
		)
	}
}

func TestJobResultResponseWriter(t *testing.T) {
	r := NewJobResult()

	r.Header().Set("X-Test", "hello")

	if _, err := r.Write([]byte("body")); err != nil {
		t.Fatal(err)
	}

	r.WriteHeader(http.StatusCreated)

	if r.Status != http.StatusCreated {
		t.Errorf(
			"Status = %d, want %d",
			r.Status,
			http.StatusCreated,
		)
	}

	if r.Headers.Get("X-Test") != "hello" {
		t.Errorf(
			"X-Test = %q, want hello",
			r.Headers.Get("X-Test"),
		)
	}

	if r.Body.String() != "body" {
		t.Errorf(
			"Body = %q, want body",
			r.Body.String(),
		)
	}
}

func TestJobRegistrarJob(t *testing.T) {
	j := newRegistrar(t)

	handler := j.Job(func(
		w http.ResponseWriter,
		r *http.Request,
		res JobResources,
	) {
		res.SetProgress(0.5)
		res.SetNotes("processing")

		w.Header().Set("Content-Type", "text/plain")
		w.WriteHeader(http.StatusCreated)
		w.Write([]byte("done"))
	})

	req := httptest.NewRequest(
		"POST",
		"/test",
		nil,
	)

	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusAccepted {
		t.Fatalf(
			"status = %d, want %d",
			rr.Code,
			http.StatusAccepted,
		)
	}

	var response map[string]string

	if err := json.Unmarshal(rr.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}

	id := response["id"]

	if id == "" {
		t.Fatal("missing job id")
	}

	// Wait for goroutine to finish.
	deadline := time.Now().Add(time.Second)

	for time.Now().Before(deadline) {
		job, err := j.Get(id)
		if err == nil && !job.Finished.IsZero() {
			break
		}
		time.Sleep(time.Millisecond)
	}

	job, err := j.Get(id)
	if err != nil {
		t.Fatal(err)
	}

	if job.Finished.IsZero() {
		t.Fatal("job did not finish")
	}

	if job.Progress != 1 {
		t.Errorf(
			"Progress = %v, want 1",
			job.Progress,
		)
	}

	if job.Notes != "processing" {
		t.Errorf(
			"Notes = %q, want processing",
			job.Notes,
		)
	}

	result, err := j.GetResult(id)
	if err != nil {
		t.Fatal(err)
	}

	if result.Status != http.StatusCreated {
		t.Errorf(
			"result status = %d, want %d",
			result.Status,
			http.StatusCreated,
		)
	}

	body, err := io.ReadAll(result.Body)
	if err != nil {
		t.Fatal(err)
	}

	if string(body) != "done" {
		t.Errorf(
			"body = %q, want done",
			string(body),
		)
	}
}
