package handler

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"os"
	"sort"
	"sync"
	"time"
	"ubco-team15/omr/internal/httpserver/dto"
	"ubco-team15/omr/internal/httpserver/middleware"
	"ubco-team15/omr/internal/sys"

	"github.com/google/uuid"
)

const (
	MaxBodySize = 200 << 20
)

//
// Errors
//

var (
	ErrJobFinished     = errors.New("cannot update a finished job")
	ErrJobNotFound     = errors.New("job not found")
	ErrJobIdConflict   = errors.New("new job could not be created because the ID is already in use")
	ErrRequestTooLarge = errors.New("request body too large")
)

//
// JobResult Implementation
//
// Jobs need to have cached results, so we need to be able to store everything
// about an HTTP response. Fortunately, that's just the headers, status code,
// and response body. For convenience we have our cached response implement the
// [http.ResponseWriter] interface so that we can inject it into regular
// handler functions.
//

type JobResult struct {
	Status  int
	Headers http.Header
	Body    *bytes.Buffer
}

var _ http.ResponseWriter = (*JobResult)(nil)

func (j *JobResult) Header() http.Header {
	return j.Headers
}

func (j *JobResult) Write(p []byte) (int, error) {
	return j.Body.Write(p)
}

func (j *JobResult) WriteHeader(statusCode int) {
	j.Status = statusCode
}

func NewJobResult() *JobResult {
	return &JobResult{
		Status:  200, // default status code
		Headers: make(http.Header),
		Body:    bytes.NewBuffer(nil),
	}
}

//
// Registrar Implementation
//

type JobDetails struct {
	Id       string
	Method   string
	Path     string
	Progress float64
	Started  time.Time
	Finished time.Time
	Success  bool
	Notes    string
}

// A place to register and track jobs.
//
// This type should be instantiated by the [NewJobRegistrar] function.
type JobRegistrar struct {
	jobResults     map[string]*JobResult
	jobs           map[string]*JobDetails
	mu             sync.RWMutex
	evictionTicker *time.Ticker
}

// Returns true if and only if the given ID is associated with a registered
// job.
func (j *JobRegistrar) IsRegistered(id string) bool {
	j.mu.RLock()
	defer j.mu.RUnlock()

	_, ok := j.jobs[id]
	return ok
}

// Retrieves the details of a job.
//
// If an error is returned, it will be [ErrJobNotFound].
func (j *JobRegistrar) Get(id string) (JobDetails, error) {
	j.mu.RLock()
	defer j.mu.RUnlock()

	job, ok := j.jobs[id]
	if !ok {
		return JobDetails{}, ErrJobNotFound
	}

	return *job, nil
}

// Retrieves the cached results for a completed job.
//
// If an error is returned, it will be [ErrJobNotFound].
func (j *JobRegistrar) GetResult(id string) (JobResult, error) {
	j.mu.RLock()
	defer j.mu.RUnlock()

	result, ok := j.jobResults[id]
	if !ok {
		return JobResult{}, ErrJobNotFound
	}

	return *result, nil
}

// Updates the progress of a previously registered job.
//
// If an error is returned, it will be [ErrJobNotFound] or [ErrJobFinished].
func (j *JobRegistrar) SetProgress(id string, progress float64) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	job := j.jobs[id]
	if job == nil {
		return ErrJobNotFound
	}

	if !job.Finished.IsZero() {
		return ErrJobFinished
	}

	job.Progress = progress
	return nil
}

// Overwrites the notes attached to a given job. If this function is never
// called, the job's notes will be blank. This method can be used to give
// human-readable context, such as the size of the job or an explanation for
// its failure.
//
// If an error is returned, it will be [ErrJobNotFound].
func (j *JobRegistrar) WriteNotes(id string, notes string) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	job := j.jobs[id]
	if job == nil {
		return ErrJobNotFound
	}

	job.Notes = notes
	return nil
}

// Registers a new job.
//
// If an error is returned, it will be [ErrJobIdConflict].
func (j *JobRegistrar) Register(
	id string,
	r *http.Request,
) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	if _, ok := j.jobs[id]; ok {
		return ErrJobIdConflict
	}

	job := JobDetails{
		Id:      id,
		Method:  r.Method,
		Path:    r.URL.Path,
		Started: time.Now(),
	}
	j.jobs[id] = &job

	return nil
}

// Updates a job's details to reflect a resolved state.
//
// If an error is returned, it will be [ErrJobNotFound] or [ErrJobFinished].
func (j *JobRegistrar) SetFinished(
	id string,
	success bool,
	result *JobResult,
) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	job, ok := j.jobs[id]
	if !ok {
		return ErrJobNotFound
	}

	if !job.Finished.IsZero() {
		return ErrJobFinished
	}

	j.jobResults[id] = result
	job.Finished = time.Now()
	job.Progress = 1.00
	job.Success = success
	return nil
}

// Unregisters all jobs older the given age (based on their creation time, not
// completion time).
func (j *JobRegistrar) evictAllOlderThan(age time.Duration) {
	j.mu.Lock()
	defer j.mu.Unlock()

	expired := make([]string, 0)
	now := time.Now()

	for key, job := range j.jobs {
		if now.Compare(job.Started.Add(age)) == 1 {
			expired = append(expired, key)
		}
	}

	for _, key := range expired {
		delete(j.jobs, key)
		delete(j.jobResults, key)
	}
}

// Creates a new job registrar.
func NewJobRegistrar(maxAge time.Duration) *JobRegistrar {
	j := &JobRegistrar{
		jobs:       make(map[string]*JobDetails, 1<<8),
		jobResults: make(map[string]*JobResult, 1<<8),
	}

	evictionTicker := time.NewTicker(min(maxAge, time.Hour))

	go func() {
		for range evictionTicker.C {
			j.evictAllOlderThan(maxAge)
		}
	}()

	j.evictionTicker = evictionTicker

	return j
}

func (j *JobRegistrar) Close() {
	j.evictionTicker.Stop()
}

//
// HTTP Handlers
//

type JobStatus struct {
	Id       string  `json:"id"`
	Method   string  `json:"method"`
	Path     string  `json:"path"`
	Progress float64 `json:"progress"`
	Started  int64   `json:"startedTimestamp"`
	Finished int64   `json:"finishedTimestamp,omitempty"`
	Success  *bool   `json:"success,omitempty"`
	Notes    string  `json:"notes"`
}

// Returns an HTTP handler that responds to requests by checking for an "id"
// query parameter and retrieving the details of the identified job.
func (j *JobRegistrar) Handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(
				w,
				"id parameter is required",
				http.StatusBadRequest,
			)
			return
		}

		job, err := j.Get(id)
		if err != nil {
			http.Error(
				w,
				"job ID not recognized",
				http.StatusNotFound,
			)
			return
		}

		if job.Finished.IsZero() {
			dto.SendJson(w, JobStatus{
				Id:       job.Id,
				Method:   job.Method,
				Path:     job.Path,
				Progress: job.Progress,
				Started:  job.Started.UnixMilli(),
				Finished: 0,
				Success:  nil,
				Notes:    job.Notes,
			})
		} else {
			dto.SendJson(w, JobStatus{
				Id:       job.Id,
				Method:   job.Method,
				Path:     job.Path,
				Progress: job.Progress,
				Started:  job.Started.UnixMilli(),
				Finished: job.Finished.UnixMilli(),
				Success:  &job.Success,
				Notes:    job.Notes,
			})
		}
	}
}

//
// Implement sort.Interface
//

type JobStatusList []*JobStatus

func (j JobStatusList) Len() int {
	return len(j)
}

func (j JobStatusList) Less(a, b int) bool {
	return j[a].Started-j[b].Started < 0
}

func (j JobStatusList) Swap(a, b int) {
	j[a], j[b] = j[b], j[a]
}

// Returns an HTTP handler that responds to requests by checking for the admin
// key on the request and then, if authorized, sending back a list of all jobs
// sorted from oldest to newest.
func (j *JobRegistrar) ListHandler(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		if authorized := s.CheckAdminKey(r); !authorized {
			http.Error(
				w,
				"only admins can retrieve all jobs",
				http.StatusUnauthorized,
			)
			return
		}

		j.mu.RLock()
		defer j.mu.RUnlock()

		jobs := make(JobStatusList, len(j.jobs))
		i := 0
		for _, job := range j.jobs {
			if job.Finished.IsZero() {
				jobs[i] = &JobStatus{
					Id:       job.Id,
					Method:   job.Method,
					Path:     job.Path,
					Progress: job.Progress,
					Started:  job.Started.UnixMilli(),
					Finished: 0,
					Success:  nil,
					Notes:    job.Notes,
				}
			} else {
				jobs[i] = &JobStatus{
					Id:       job.Id,
					Method:   job.Method,
					Path:     job.Path,
					Progress: job.Progress,
					Started:  job.Started.UnixMilli(),
					Finished: job.Finished.UnixMilli(),
					Success:  &job.Success,
					Notes:    job.Notes,
				}
			}
			i++
		}

		sort.Sort(jobs)

		dto.SendCompressedJson(w, r, jobs)
	}
}

// Returns an HTTP handler that responds to requests by sending back the cached
// response or 404 if the job is not registered.
func (j *JobRegistrar) ResultHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(
				w,
				"id parameter is required",
				http.StatusBadRequest,
			)
			return
		}

		result, err := j.GetResult(id)
		if err != nil {
			if j.IsRegistered(id) {
				http.Error(
					w,
					"the job matching the given ID does not have a result yet",
					http.StatusNotFound,
				)
				return
			}
			http.Error(
				w,
				"no job matches the given ID",
				http.StatusNotFound,
			)
		}

		for key, vals := range result.Headers {
			for _, val := range vals {
				w.Header().Add(key, val)
			}
		}
		w.WriteHeader(result.Status)
		w.Write(result.Body.Bytes())
	}
}

//
// Job Wrapper
//
// The Job wrapper is meant to take an existing handler function and convert it
// into an asynchronous job. There is one caveat, which is that the wrapped
// function should accept an extra [JobResources] parameter. It doesn't need to
// do anything with the argument, but it may use it to provide updates on its
// progress.
//

// This interface is exposed to handler functions that can be job-ified.
type JobResources interface {
	SetProgress(float64) // 0.0 to 1.0.
	SetNotes(string)     // Attaches notes to the job status.
}

// Updates the job progress. Unlike calling [JobResources.SetProgress]
// directly, this function won't panic when j is nil.
func SetProgress(j JobResources, progress float64) {
	if j != nil {
		j.SetProgress(progress)
	}
}

// Updates the job notes. Unlike calling [JobResources.SetNotes] directly, this
// function won't panic when j is nil.
func SetNotes(j JobResources, notes string) {
	if j != nil {
		j.SetNotes(notes)
	}
}

// A job-ifiable handler function.
type JobHandlerFunc func(http.ResponseWriter, *http.Request, JobResources)

// An implementation of [JobResources].
type jobRes struct {
	r  *JobRegistrar
	id string
}

var _ JobResources = (*jobRes)(nil)

func (j *jobRes) SetProgress(progress float64) {
	progress = max(0, progress)
	progress = min(1, progress)
	j.r.SetProgress(j.id, progress)
}

func (j *jobRes) SetNotes(notes string) {
	j.r.WriteNotes(j.id, notes)
}

//
// TODO: Make distinct Sync- and Async- wrappers. Synchronous jobs are tracked,
// but their results are not cached. They return results like normal.
//

// Wraps the given job-ifiable handler function to automatically run it as an
// asynchronous job.
func (j *JobRegistrar) Job(handler JobHandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		id := uuid.New().String()
		if err := j.Register(id, r); err != nil {
			http.Error(
				w,
				"error creating job. UUID collision?",
				http.StatusInternalServerError,
			)
			return
		}

		copiedReq, cleanup, err := copyRequest(r, MaxBodySize)
		r.Body.Close()
		if err != nil {
			http.Error(
				w,
				"error reading request body: "+err.Error(),
				http.StatusBadRequest,
			)
			return
		}

		resources := jobRes{id: id, r: j}
		result := NewJobResult()

		w.WriteHeader(http.StatusAccepted)
		dto.SendJson(w, map[string]string{
			"id": id,
		})

		go func() {
			defer cleanup()
			sys.Log("job started", "id", id)
			defer sys.Log("job finished", "id", id)
			defer middleware.RecoverAndRespond(w, r)

			handler(result, copiedReq, &resources)

			j.SetFinished(
				id,
				result.Status >= 200 && result.Status < 300,
				result,
			)
		}()
	}
}

//
// TODO: Implement a proper temp buffer that frees its memory when closed.
//

// Creates a copy of an HTTP request whose body is backed by a temporary file.
// The returned cleanup function must be called when the copied request is no
// longer needed.
func copyRequest(
	r *http.Request,
	maxBodySize int64,
) (*http.Request, func(), error) {

	req := r.Clone(r.Context())

	if r.Body == nil {
		return req, func() {}, nil
	}

	//
	// Copy the request body into a temporary file.
	//

	tmp, err := os.CreateTemp("", "omr-job-*")
	if err != nil {
		return nil, nil, err
	}

	cleanup := func() {
		tmp.Close()
		os.Remove(tmp.Name())
	}

	n, err := io.Copy(tmp, io.LimitReader(r.Body, maxBodySize+1))
	if err != nil {
		cleanup()
		return nil, nil, err
	}

	if n > maxBodySize {
		cleanup()
		return nil, nil, ErrRequestTooLarge
	}

	//
	// Rewind and attach the file to the copied request.
	//

	if _, err := tmp.Seek(0, io.SeekStart); err != nil {
		cleanup()
		return nil, nil, err
	}

	req.Body = tmp
	req.ContentLength = n

	return req, cleanup, nil
}
