package sys

import (
	"sync"
)

// An implementation of a thread-safe ring buffer.
type RingBuffer[T any] struct {
	length   int
	capacity int
	elements []T
	idx      int
	mu       sync.RWMutex
}

// Creates a new thread-safe ring buffer with the given capacity.
func NewRingBuffer[T any](cap int) *RingBuffer[T] {
	rb := RingBuffer[T]{}
	rb.capacity = cap
	rb.elements = make([]T, cap)
	return &rb
}

// Adds a new item to the ring buffer.
func (r *RingBuffer[T]) Add(item T) {

	r.mu.Lock()
	defer r.mu.Unlock()

	r.elements[r.idx] = item
	r.idx = (r.idx + 1) % r.capacity
	r.length = min(r.capacity, r.length+1)
}

func (r *RingBuffer[T]) Len() int {
	return r.length
}

func (r *RingBuffer[T]) Flush() {

	r.mu.Lock()
	defer r.mu.Unlock()

	r.length = 0
	r.elements = make([]T, r.capacity)
	r.idx = 0
}

// Retrieves the n most recently added items and copies them into a newly-
// allocated slice. The items will be ordered from oldest to newest.
func (r *RingBuffer[T]) Get(n int) []T {
	if n <= 0 {
		return nil
	}

	r.mu.RLock()
	defer r.mu.RUnlock()

	n = min(n, r.length)

	items := make([]T, n)
	for i := range n {
		idx := r.idx - 1 - i
		if idx < 0 {
			idx = r.capacity + idx
		}
		items[n-i-1] = r.elements[idx]
	}

	return items
}
