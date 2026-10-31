package fs

import (
	"encoding/binary"
	"image"
	"io"
	"os"
	"path/filepath"

	"github.com/pierrec/lz4/v4"
	"gocv.io/x/gocv"
)

//
// Local ImageStore implementation.
//

type localImageStore struct {
	root string // The path to the root directory of the store.
}

func NewLocalImageStore(rootDir string) (ImageStore, error) {
	if err := os.MkdirAll(rootDir, 0755); err != nil {
		return nil, err
	}

	return &localImageStore{root: rootDir}, nil
}

func (s *localImageStore) Get(key string) (image.Image, error) {
	f, err := os.Open(filepath.Join(s.root, key))
	if err != nil {
		return nil, err
	}
	defer f.Close()

	img, err := DecodeImg(f)
	if err != nil {
		return nil, err
	}

	return img, nil
}

func (s *localImageStore) Set(key string, img image.Image) error {
	w, err := os.Create(filepath.Join(s.root, key))
	if err != nil {
		return err
	}
	defer w.Close()

	err = EncodeImg(w, img)
	return err
}

func (s *localImageStore) SetBytes(key string, buf []byte) error {
	return os.WriteFile(
		filepath.Join(s.root, key),
		buf,
		0755,
	)
}

func (s *localImageStore) Delete(key string) error {
	return os.Remove(filepath.Join(s.root, key))
}

func (s *localImageStore) Open(key string) (io.ReadCloser, error) {
	return os.Open(filepath.Join(s.root, key))
}

func (s *localImageStore) Count() (int, uint64) {
	files, err := os.ReadDir(s.root)
	if err != nil {
		return 0, 0
	}

	var totalBytes uint64
	for _, file := range files {
		info, err := file.Info()
		if err != nil {
			return 0, 0
		}
		totalBytes += uint64(info.Size())
	}

	return len(files), totalBytes
}

//
// Local MatStore implementation.
//

type localMatStore struct {
	root string // The path to the root directory of the store.
}

func NewLocalMatStore(rootDir string) (MatStore, error) {
	if err := os.MkdirAll(rootDir, 0755); err != nil {
		return nil, err
	}

	return &localMatStore{root: rootDir}, nil
}

//
// Rather than storing OpenCV matrices as images, which requires inefficient
// encoding/decoding, we can store them a bit more neatly by just using the
// underlying byte buffer that OpenCV maintains. The file format we use is
// described below.
//
// OpenCV matrices have the following data that needs to be stored in order to
// recreate them:
// - the rows and columns in the matrix,
// - the matrix type flag, and
// - the bytes that store the data.
// In order to store this data, we will write it into a binary file that
// includes the dimensions and matrix type as part of a header.
//
//        [int32][int32][int32][bytes...]
//         │      │      │      └─ the bytes buffer for the matrix
//         │      │      └──────── the matrix type flag
//         │      └─────────────── the number of columns
//         └────────────────────── the number of rows
//
// The integers are stored in little endian format and the bytes buffer is
// compressed with the LZ4 algorithm.
//

func (s *localMatStore) Set(key string, mat *gocv.Mat) error {

	buf, err := mat.DataPtrUint8()
	if err != nil {
		return err
	}

	header := make([]byte, 12)
	binary.Encode(header[0:4], binary.LittleEndian, int32(mat.Rows()))
	binary.Encode(header[4:8], binary.LittleEndian, int32(mat.Cols()))
	binary.Encode(header[8:12], binary.LittleEndian, int32(mat.Type()))

	w, err := os.Create(filepath.Join(s.root, key))
	if err != nil {
		return err
	}
	defer w.Close()

	if _, err := w.Write(header); err != nil {
		return err
	}

	compressedWriter := lz4.NewWriter(w)
	defer compressedWriter.Close()

	if _, err := compressedWriter.Write(buf); err != nil {
		return err
	}

	return nil
}

func (s *localMatStore) Get(key string) (*gocv.Mat, error) {
	f, err := os.Open(filepath.Join(s.root, key))
	if err != nil {
		return nil, err
	}
	defer f.Close()

	header := make([]byte, 12)
	if _, err := io.ReadFull(f, header); err != nil {
		return nil, err
	}
	var rows, cols, mt int32
	binary.Decode(header[0:4], binary.LittleEndian, &rows)
	binary.Decode(header[4:8], binary.LittleEndian, &cols)
	binary.Decode(header[8:12], binary.LittleEndian, &mt)

	compressedReader := lz4.NewReader(f)

	buf, err := io.ReadAll(compressedReader)
	if err != nil {
		return nil, err
	}

	mat, err := gocv.NewMatFromBytes(
		int(rows),
		int(cols),
		gocv.MatType(mt),
		buf,
	)
	if err != nil {
		return nil, err
	}

	return &mat, nil
}

func (s *localMatStore) Delete(key string) error {
	return os.Remove(filepath.Join(s.root, key))
}

func (s *localMatStore) Count() (int, uint64) {
	files, err := os.ReadDir(s.root)
	if err != nil {
		return 0, 0
	}

	var totalBytes uint64
	for _, file := range files {
		info, err := file.Info()
		if err != nil {
			return 0, 0
		}
		totalBytes += uint64(info.Size())
	}

	return len(files), totalBytes
}
