//go:build linux && cgo

package sys

import (
	"runtime/debug"
)

/*
#include <stdio.h>

#if defined(__GLIBC__)
#include <malloc.h>

static void trim_malloc() {
    malloc_trim(0);
}

#else

static void trim_malloc() {
}

#endif
*/
import "C"

// Attempts to release as much memory to the OS as possible. Be warned that
// forcing a GC may pause the program momentarily and it should not be used too
// often.
func Tidy() {
	debug.FreeOSMemory()
	C.trim_malloc()
}
