package sys

import (
	"testing"
	"time"
)

func TestUptime(t *testing.T) {
	u1 := Uptime()
	if u1 < 0 {
		t.Fatalf("uptime should never be negative, got %v", u1)
	}

	time.Sleep(50 * time.Millisecond)

	u2 := Uptime()
	if u2 < u1 {
		t.Fatalf("uptime decreased: %v -> %v", u1, u2)
	}
}

func TestCurrentCpuInfo(t *testing.T) {
	info, err := currentCpuInfo()
	if err != nil {
		t.Fatalf("currentCpuInfo() returned error: %v", err)
	}

	if info.Description == "" {
		t.Error("CPU description should not be empty")
	}

	if info.OverallPercent < 0 || info.OverallPercent > 100 {
		t.Errorf("overall CPU percent out of range: %v", info.OverallPercent)
	}

	if info.FrequencyMhz <= 0 {
		t.Errorf("CPU frequency should be positive, got %v", info.FrequencyMhz)
	}

	if len(info.Threads) == 0 {
		t.Error("expected at least one CPU thread")
	}

	for i, thread := range info.Threads {
		if thread.Percent < 0 || thread.Percent > 100 {
			t.Errorf("thread %d CPU percent out of range: %v", i, thread.Percent)
		}
	}
}

func TestCurrentMemInfo(t *testing.T) {
	info, err := currentMemInfo()
	if err != nil {
		t.Fatalf("currentMemInfo() returned error: %v", err)
	}

	if info.Free == 0 {
		t.Error("total available memory should be positive")
	}
}

func TestCurrentDiskInfo(t *testing.T) {
	info, err := currentDiskInfo()
	if err != nil {
		t.Fatalf("currentDiskInfo returned error: %v", err)
	}

	if info.Total == 0 {
		t.Error("disk total should be positive")
	}

	if info.Free > info.Total {
		t.Errorf("free space exceeds total (%d > %d)", info.Free, info.Total)
	}

	if info.Used > info.Total {
		t.Errorf("used space exceeds total (%d > %d)", info.Used, info.Total)
	}
}

func TestCpuHistory(t *testing.T) {
	h := CpuHistory(100)

	if len(h) > 100 {
		t.Fatalf("returned %d entries, expected at most 100", len(h))
	}

	for i, info := range h {
		if info.Description == "" {
			t.Errorf("entry %d has empty description", i)
		}

		if info.OverallPercent < 0 || info.OverallPercent > 100 {
			t.Errorf("entry %d overall percent out of range", i)
		}
	}
}

func TestMemHistory(t *testing.T) {
	h := MemHistory(100)

	if len(h) > 100 {
		t.Fatalf("returned %d entries, expected at most 100", len(h))
	}

	for i, info := range h {
		if info.Free == 0 {
			t.Errorf("entry %d has zero total memory", i)
		}
	}
}

func TestDiskHistory(t *testing.T) {
	h := DiskHistory(100)

	if len(h) > 100 {
		t.Fatalf("returned %d entries, expected at most 100", len(h))
	}

	for i, info := range h {
		if info.Total == 0 {
			t.Errorf("entry %d has zero total disk", i)
		}

		if Docker() {
			// Docker may give inconsistent counts for free/used/total memory,
			// so the following condition is not guaranteed to hold. If there
			// is a substitute condition or an alternative, consistent
			// implementation, I do not know of it.
			continue
		}

		if info.Free+info.Used != info.Total {
			t.Errorf("entry %d disk accounting invalid", i)
		}
	}
}

func TestHistoryRequestZero(t *testing.T) {
	if got := CpuHistory(0); len(got) != 0 {
		t.Errorf("CpuHistory(0) returned %d entries", len(got))
	}

	if got := MemHistory(0); len(got) != 0 {
		t.Errorf("MemHistory(0) returned %d entries", len(got))
	}

	if got := DiskHistory(0); len(got) != 0 {
		t.Errorf("DiskHistory(0) returned %d entries", len(got))
	}
}

func TestHistoryRequestNegative(t *testing.T) {
	if got := CpuHistory(-1); len(got) != 0 {
		t.Errorf("CpuHistory(-1) returned %d entries", len(got))
	}

	if got := MemHistory(-1); len(got) != 0 {
		t.Errorf("MemHistory(-1) returned %d entries", len(got))
	}

	if got := DiskHistory(-1); len(got) != 0 {
		t.Errorf("DiskHistory(-1) returned %d entries", len(got))
	}
}
