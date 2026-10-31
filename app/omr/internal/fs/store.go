/*
This package provides the means to store files ("fs" is short for "file
storage").
*/
package fs

import (
	"errors"
	"image"
	"io"

	"gocv.io/x/gocv"
)

var (
	ErrNotFound = errors.New("the requested resource was not found")
)

// Represents an image store, implementing a map-like interface to save and
// load images to persistent storage.
type ImageStore interface {
	// Retrieves an image from the store with the given key.
	Get(key string) (image.Image, error)
	// Puts an image in the store and assigns it the given key. Any
	// pre-existing image with the same key will be overwritten.
	Set(key string, img image.Image) error
	// Works the same as Set, except it stores the raw bytes and assumes that
	// they represent an image that is correctly encoded with the format
	// specified by ImgContentType. It is strongly recommended that image
	// encoding is verified in some way before calling this function.
	SetBytes(key string, buf []byte) error
	// Deletes an image from the store.
	Delete(key string) error
	// Opens an existing image for reading.
	Open(key string) (io.ReadCloser, error)
	// Counts the number of stored images and the total number of bytes they
	// occupy.
	Count() (int, uint64)
}

// Represents an OpenCV matrix store, implementing a map-like interface to
// save and load matrices to/from persistent storage.
type MatStore interface {
	// Saves an OpenCV matrix under the given key. If a matrix already exists
	// with the given key, it will be overwritten.
	Set(key string, mat *gocv.Mat) error
	// Loads an OpenCV matrix by the given key. If no matrix is associated with
	// the key, then [ErrNotFound] is returned.
	Get(key string) (*gocv.Mat, error)
	// Deletes a stored matrix.
	Delete(key string) error
	// Counts the number of stored matrices and the total number of bytes they
	// occupy.
	Count() (int, uint64)
}
