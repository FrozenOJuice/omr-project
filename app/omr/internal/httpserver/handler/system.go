package handler

import (
	"net/http"
	"runtime"
	"strconv"
	"ubco-team15/omr/internal/httpserver/dto"
	"ubco-team15/omr/internal/sys"
)

//
// Helpers
//

const defaultLimit = 30

// Returns the "limit" parameter from the request's query string, parsed as a
// positive integer. If anything goes wrong, an error response will be sent and
// the second return value will be set to false.
func parseLimit(w http.ResponseWriter, r *http.Request) (int, bool) {
	limit := defaultLimit
	limitStr := r.URL.Query().Get("limit")
	if limitStr != "" {
		limitVal, err := strconv.Atoi(limitStr)
		if err != nil || limitVal < 1 {
			http.Error(
				w,
				"limit parameter must be a positive integer",
				http.StatusBadRequest,
			)
			return 0, false
		}
		limit = limitVal
	}

	return limit, true
}

//
// Public System Info
//

type ResourceUtilization struct {
	CpuHistory    []sys.CpuInfo `json:"cpuHistory"`
	MemoryHistory []sys.MemInfo `json:"memoryHistory"`
	Disk          struct {
		Usage    sys.DiskInfo `json:"usage"`
		OmrUsage struct {
			Database         uint64 `json:"database"`
			NumberOfMatrices int    `json:"numberOfMatrices"`
			Matrices         uint64 `json:"matrices"`
			NumberOfPictures int    `json:"numberOfPictures"`
			Pictures         uint64 `json:"pictures"`
			Total            uint64 `json:"total"`
		} `json:"omrUsage"`
	} `json:"disk"`
	MemoryPeak uint64 `json:"memoryPeak"`
	Uptime     uint64 `json:"uptime"`
}

func GetResourceUtilization(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		limit, ok := parseLimit(w, r)
		if !ok {
			return
		}

		result := ResourceUtilization{}

		result.CpuHistory = sys.CpuHistory(limit)
		result.MemoryHistory = sys.MemHistory(limit)

		diskHistory := sys.DiskHistory(1)
		if len(diskHistory) > 0 {
			result.Disk.Usage = diskHistory[0]
		}

		result.MemoryPeak = sys.PeakMem()
		result.Uptime = uint64(sys.Uptime().Seconds())

		dbSize := s.DBSize()
		nPictures, picturesSize := s.CountPictures()
		nMats, matsSize := s.CountMats()

		result.Disk.OmrUsage.Database = dbSize
		result.Disk.OmrUsage.Matrices = matsSize
		result.Disk.OmrUsage.NumberOfMatrices = nMats
		result.Disk.OmrUsage.Pictures = picturesSize
		result.Disk.OmrUsage.NumberOfPictures = nPictures
		result.Disk.OmrUsage.Total = dbSize + matsSize + picturesSize

		dto.SendCompressedJson(w, r, result)
	}
}

func GetLogs(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		limit, ok := parseLimit(w, r)
		if !ok {
			return
		}

		w.Header().Add("Content-Type", "text/plain")
		sys.DumpLogs(w, limit)
	}
}

type CpuUsageSample struct {
	Overall   float64   `json:"overall"`
	PerThread []float64 `json:"perThread"`
}

type DetailedCpuInfo struct {
	Description  string           `json:"description"`
	FrequencyMhz float64          `json:"frequencyMhz"`
	MaxThreads   int              `json:"maxThreads"`
	UsageSamples []CpuUsageSample `json:"usageSamples"`
}

func GetCpuInfo(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		limit, ok := parseLimit(w, r)
		if !ok {
			return
		}

		samples := sys.CpuHistory(limit)
		result := DetailedCpuInfo{
			UsageSamples: make([]CpuUsageSample, len(samples)),
		}
		for i, s := range samples {
			result.UsageSamples[i].Overall = s.OverallPercent
			result.UsageSamples[i].PerThread = make([]float64, len(s.Threads))
			for j, t := range s.Threads {
				result.UsageSamples[i].PerThread[j] = t.Percent
			}
		}
		lastSample := samples[len(samples)-1]

		result.Description = lastSample.Description
		result.FrequencyMhz = lastSample.FrequencyMhz
		result.MaxThreads = runtime.GOMAXPROCS(0)

		dto.SendCompressedJson(w, r, result)
	}
}

type DetailedMemoryInfo struct {
	UsageSamples []sys.MemInfo `json:"usageSamples"`
}

func GetMemoryInfo(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		limit, ok := parseLimit(w, r)
		if !ok {
			return
		}

		samples := sys.MemHistory(limit)

		dto.SendCompressedJson(w, r, DetailedMemoryInfo{
			UsageSamples: samples,
		})

	}
}

//
// Admin Endpoints
//

func CheckAdminKey(s ServerResources) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if authenticated := s.CheckAdminKey(r); !authenticated {
			http.Error(
				w,
				"incorrect admin key",
				http.StatusUnauthorized,
			)
		}
	}
}
