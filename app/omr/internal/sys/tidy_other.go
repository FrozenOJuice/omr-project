//go:build !linux || !cgo

package sys

import "runtime/debug"

// Attempts to release as much memory to the OS as possible. Be warned that
// forcing a GC may pause the program momentarily and it should not be used too
// often.
func Tidy() {
	debug.FreeOSMemory()
}
