/*
This package provides an interface to collect information about the system in
which the OMR is running. It passively checks certain statistics and caches
them in memory and on disk to provide stable access, tracks certain configured
constants, and exposes logging functions that can be used globally.
*/
package sys

import (
	"os"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/process"
)

//
// In this file we implement functionality to periodically check the system's
// resource utilization (CPU, memory), cache it, and retrieve it.
//

const (
	PollPeriod  = time.Second // Poll CPU/memory/disk stats every 1 second
	HistorySize = 1 << 12     // Hold up to this many recorded stats.
)

var (
	cpuHistory  *RingBuffer[CpuInfo]
	memHistory  *RingBuffer[MemInfo]
	diskHistory *RingBuffer[DiskInfo]

	// The maximum amount of memory used by the OMR since startup.
	lifetimeMaxMem uint64
)

func init() {

	cpuHistory = NewRingBuffer[CpuInfo](HistorySize)
	memHistory = NewRingBuffer[MemInfo](HistorySize)
	diskHistory = NewRingBuffer[DiskInfo](HistorySize)

	cpu, err := currentCpuInfo()
	if err != nil {
		panic("error getting CPU info: " + err.Error())
	}

	mem, err := currentMemInfo()
	if err != nil {
		panic("error getting memory info: " + err.Error())
	}

	disk, err := currentDiskInfo()
	if err != nil {
		panic("error getting disk info: " + err.Error())
	}

	cpuHistory.Add(cpu)
	memHistory.Add(mem)
	diskHistory.Add(disk)

	lifetimeMaxMem = mem.InUseOmr

	go func() {
		for range time.Tick(PollPeriod) {

			//
			// We ignore errors below, under the assumption that if there are
			// errors, they would've occurred on the initialization. But it's
			// also not a big deal if these values are zero since they don't
			// dictate any behavior.
			//

			cpu, _ := currentCpuInfo()
			cpuHistory.Add(cpu)

			mem, _ := currentMemInfo()
			memHistory.Add(mem)

			disk, _ := currentDiskInfo()
			diskHistory.Add(disk)

			lifetimeMaxMem = max(lifetimeMaxMem, mem.InUseOmr)

		}
	}()
}

var startupTime = time.Now()

// Returns the duration that the application has been running.
func Uptime() time.Duration {
	return time.Since(startupTime)
}

// Returns true if the application is running inside of a Docker container.
func Docker() bool {
	_, err := os.Stat("/docker.env")
	return err != nil
}

// Returns the peak memory usage for the OMR since startup.
func PeakMem() uint64 {
	return lifetimeMaxMem
}

//
// CPU
//

// Gets up to the n most recent recorded CPU stats. CPU stats are collected at
// a rate determined by [PollPeriod]. The maximum number of stats that can be
// retrieved is determined by [HistorySize].
func CpuHistory(n int) []CpuInfo {
	return cpuHistory.Get(n)
}

type CpuInfo struct {
	Description    string  `json:"description"`
	OverallPercent float64 `json:"overallPercent"`
	FrequencyMhz   float64 `json:"mhz"`
	Threads        []struct {
		Percent float64 `json:"percent"`
	} `json:"threads"`
}

func currentCpuInfo() (CpuInfo, error) {
	newInfo := CpuInfo{}

	cpuInfo, err := cpu.Info()
	if err != nil {
		return CpuInfo{}, err
	}

	if len(cpuInfo) > 0 {
		newInfo.Description = cpuInfo[0].ModelName
		newInfo.FrequencyMhz = cpuInfo[0].Mhz
	}

	overall, err := cpu.Percent(0, false)
	if err != nil {
		return CpuInfo{}, err
	}

	if len(overall) > 0 {
		newInfo.OverallPercent = overall[0]
	}

	corePercents, err := cpu.Percent(0, true)
	if err != nil {
		return CpuInfo{}, err
	}

	newInfo.Threads = make([]struct {
		Percent float64 `json:"percent"`
	}, len(corePercents))

	for i, percent := range corePercents {
		newInfo.Threads[i].Percent = percent
	}

	return newInfo, nil
}

//
// Memory
//

// Gets up to the n most recent recorded memory usage stats. Memory stats are
// collected at a rate determined by [PollPeriod]. The maximum number of stats
// that can be retrieved is determined by [HistorySize].
func MemHistory(n int) []MemInfo {
	return memHistory.Get(n)
}

type MemInfo struct {
	InUseOmr   uint64 `json:"inUseOmr"`
	InUseOther uint64 `json:"inUseOther"`
	Free       uint64 `json:"free"`
}

func currentMemInfo() (MemInfo, error) {
	newInfo := MemInfo{}

	vmem, err := mem.VirtualMemory()
	if err != nil {
		return MemInfo{}, nil
	}

	newInfo.Free = vmem.Available

	proc, err := process.NewProcess(int32(os.Getpid()))
	if err != nil {
		return MemInfo{}, nil
	}

	rss, err := proc.MemoryInfo()
	if err != nil {
		return MemInfo{}, nil
	}

	newInfo.InUseOmr = rss.RSS
	newInfo.InUseOther = vmem.Used - rss.RSS

	return newInfo, nil
}

//
// Disk
//

// Gets up to the n most recent recorded disk usage stats. Disk stats are
// collected at a rate determined by [PollPeriod]. The maximum number of
// stats that can be retrieved is determined by [HistorySize].
func DiskHistory(n int) []DiskInfo {
	return diskHistory.Get(n)
}

type DiskInfo struct {
	Total uint64 `json:"total"`
	Free  uint64 `json:"free"`
	Used  uint64 `json:"used"`
}

func currentDiskInfo() (DiskInfo, error) {
	d, err := disk.Usage("/")
	if err != nil {
		return DiskInfo{}, err
	}

	return DiskInfo{
		Total: d.Total,
		Free:  d.Free,
		Used:  d.Used,
	}, nil
}
