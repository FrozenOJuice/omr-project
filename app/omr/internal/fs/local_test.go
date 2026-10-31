package fs

import (
	"bytes"
	"embed"
	"io"
	"testing"

	"gocv.io/x/gocv"
)

//go:embed testdata/*
var testData embed.FS

//
// Tests
//

func TestLocalImageStore(t *testing.T) {

	store, err := NewLocalImageStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	r, err := testData.Open("testdata/sample_image.jpg")
	if err != nil {
		t.Error("error reading test image: " + err.Error())
	}
	defer r.Close()

	srcImg, err := DecodeImg(r)
	if err != nil {
		t.Error("error decoding test image: " + err.Error())
	}

	name := "sample.jpg"

	if img, _ := store.Get(name); img != nil {
		t.Error("image already exists in store")
	}

	err = store.Set(name, srcImg)
	if err != nil {
		t.Error("error putting image: " + err.Error())
	}

	if _, err := store.Get(name); err != nil {
		t.Error("error getting image: " + err.Error())
	}

	err = store.Delete(name)
	if err != nil {
		t.Error("error deleting image: " + err.Error())
	}

	if img, _ := store.Get(name); img != nil {
		t.Error("image exists after deletion")
	}
}

func TestLocalMatStore(t *testing.T) {

	s, err := NewLocalMatStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
	if mat.Empty() {
		t.Fatal("failed to read source image")
	}
	defer mat.Close()

	s.Set("testkey", &mat)

	loaded, err := s.Get("testkey")
	if err != nil {
		t.Fatal(err)
	}
	defer loaded.Close()

	if loaded.Cols() != mat.Cols() {
		t.Fatalf("expected %d columns, got %d", mat.Cols(), loaded.Cols())
	}

	if loaded.Rows() != mat.Rows() {
		t.Fatalf("expected %d rows, got %d", mat.Rows(), loaded.Rows())
	}

	if loaded.Type() != mat.Type() {
		t.Fatalf("expected matrix type %d, got %d", mat.Type(), loaded.Type())
	}

	for i := range mat.Rows() {
		for j := range mat.Cols() {
			for k := range mat.Channels() {
				if mat.GetUCharAt3(i, j, k) != loaded.GetUCharAt3(i, j, k) {
					t.Fatalf(
						"expected (%d,%d,%d) to have %d, got %d",
						i, j, k,
						mat.GetUCharAt3(i, j, k),
						loaded.GetUCharAt3(i, j, k),
					)
				}
			}
		}
	}
}

func TestLocalImageStoreSetBytes(t *testing.T) {
	store, err := NewLocalImageStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	r, err := testData.Open("testdata/sample_image.jpg")
	if err != nil {
		t.Fatal("error reading test image: " + err.Error())
	}
	defer r.Close()

	srcImg, err := DecodeImg(r)
	if err != nil {
		t.Fatal("error decoding test image: " + err.Error())
	}

	// Encode the image to bytes.
	buf := bytes.Buffer{}
	if err := EncodeImg(&buf, srcImg); err != nil {
		t.Fatal("error encoding test image: " + err.Error())
	}

	name := "sample.jpg"

	err = store.SetBytes(name, buf.Bytes())
	if err != nil {
		t.Fatal("error putting image bytes: " + err.Error())
	}

	img, err := store.Get(name)
	if err != nil {
		t.Fatal("error getting image: " + err.Error())
	}

	if img.Bounds() != srcImg.Bounds() {
		t.Fatalf(
			"expected bounds %v, got %v",
			srcImg.Bounds(),
			img.Bounds(),
		)
	}
}

func TestLocalImageStoreOpen(t *testing.T) {
	store, err := NewLocalImageStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	r, err := testData.Open("testdata/sample_image.jpg")
	if err != nil {
		t.Fatal("error reading test image: " + err.Error())
	}
	defer r.Close()

	srcImg, err := DecodeImg(r)
	if err != nil {
		t.Fatal("error decoding test image: " + err.Error())
	}

	name := "sample.jpg"

	if err := store.Set(name, srcImg); err != nil {
		t.Fatal("error putting image: " + err.Error())
	}

	reader, err := store.Open(name)
	if err != nil {
		t.Fatal("error opening image: " + err.Error())
	}
	defer reader.Close()

	img, err := DecodeImg(reader)
	if err != nil {
		t.Fatal("error decoding opened image: " + err.Error())
	}

	if img.Bounds() != srcImg.Bounds() {
		t.Fatalf(
			"expected bounds %v, got %v",
			srcImg.Bounds(),
			img.Bounds(),
		)
	}
}

func TestLocalImageStoreOpenMissing(t *testing.T) {
	store, err := NewLocalImageStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	if _, err = store.Open("missing.jpg"); err == nil {
		t.Fatalf("expected error opening missing file, got %v", err)
	}
}

func TestLocalMatStoreDelete(t *testing.T) {
	store, err := NewLocalMatStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
	if mat.Empty() {
		t.Fatal("failed to read source image")
	}
	defer mat.Close()

	err = store.Set("testkey", &mat)
	if err != nil {
		t.Fatal("error storing matrix: " + err.Error())
	}

	if _, err := store.Get("testkey"); err != nil {
		t.Fatal("error loading matrix before deletion: " + err.Error())
	}

	if err := store.Delete("testkey"); err != nil {
		t.Fatal("error deleting matrix: " + err.Error())
	}

	if _, err := store.Get("testkey"); err == nil {
		t.Fatalf("expected error getting after deletion, got %v", err)
	}
}

func TestImageStoreCount(t *testing.T) {
	t.Run("Empty", func(t *testing.T) {
		store, err := NewLocalImageStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		count, bytes := store.Count()

		if count != 0 {
			t.Errorf("count = %d, want 0", count)
		}
		if bytes != 0 {
			t.Errorf("bytes = %d, want 0", bytes)
		}
	})

	t.Run("AddDelete", func(t *testing.T) {
		store, err := NewLocalImageStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		img, err := testData.Open("testdata/sample_image.jpg")
		if err != nil {
			t.Fatal(err)
		}
		defer img.Close()

		buf, err := io.ReadAll(img)
		if err != nil {
			t.Fatal(err)
		}

		if err := store.SetBytes("a", buf); err != nil {
			t.Fatal(err)
		}

		count, bytes := store.Count()
		if count != 1 {
			t.Errorf("count = %d, want 1", count)
		}
		if bytes == 0 {
			t.Error("expected non-zero byte count")
		}

		if err := store.Delete("a"); err != nil {
			t.Fatal(err)
		}

		count, bytes = store.Count()
		if count != 0 {
			t.Errorf("count = %d, want 0", count)
		}
		if bytes != 0 {
			t.Errorf("bytes = %d, want 0", bytes)
		}
	})

	t.Run("Overwrite", func(t *testing.T) {
		store, err := NewLocalImageStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		img, err := testData.Open("testdata/sample_image.jpg")
		if err != nil {
			t.Fatal(err)
		}
		defer img.Close()

		buf, err := io.ReadAll(img)
		if err != nil {
			t.Fatal(err)
		}

		if err := store.SetBytes("a", buf); err != nil {
			t.Fatal(err)
		}
		if err := store.SetBytes("a", buf); err != nil {
			t.Fatal(err)
		}

		count, _ := store.Count()
		if count != 1 {
			t.Errorf("count = %d, want 1", count)
		}
	})
}

func TestMatStoreCount(t *testing.T) {
	t.Run("Empty", func(t *testing.T) {
		store, err := NewLocalMatStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		count, bytes := store.Count()

		if count != 0 {
			t.Errorf("count = %d, want 0", count)
		}
		if bytes != 0 {
			t.Errorf("bytes = %d, want 0", bytes)
		}
	})

	t.Run("AddDelete", func(t *testing.T) {
		store, err := NewLocalMatStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
		defer mat.Close()

		if err := store.Set("a", &mat); err != nil {
			t.Fatal(err)
		}

		count, bytes := store.Count()
		if count != 1 {
			t.Errorf("count = %d, want 1", count)
		}
		if bytes == 0 {
			t.Error("expected non-zero byte count")
		}

		if err := store.Delete("a"); err != nil {
			t.Fatal(err)
		}

		count, bytes = store.Count()
		if count != 0 {
			t.Errorf("count = %d, want 0", count)
		}
		if bytes != 0 {
			t.Errorf("bytes = %d, want 0", bytes)
		}
	})

	t.Run("Overwrite", func(t *testing.T) {
		store, err := NewLocalMatStore(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}

		mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
		defer mat.Close()

		if err := store.Set("a", &mat); err != nil {
			t.Fatal(err)
		}
		if err := store.Set("a", &mat); err != nil {
			t.Fatal(err)
		}

		count, _ := store.Count()
		if count != 1 {
			t.Errorf("count = %d, want 1", count)
		}
	})
}

//
// Benchmarks
//

func BenchmarkLocalMatLoad(b *testing.B) {
	s, err := NewLocalMatStore(b.TempDir())
	if err != nil {
		b.Fatal(err)
	}

	mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
	if mat.Empty() {
		b.Fatal("failed to read source image")
	}

	s.Set("testkey", &mat)
	mat.Close()

	for b.Loop() {
		mat, _ := s.Get("testkey")
		mat.Close()
	}
}

func BenchmarkLocalMatSave(b *testing.B) {
	s, err := NewLocalMatStore(b.TempDir())
	if err != nil {
		b.Fatal(err)
	}

	mat := gocv.IMRead("testdata/sample_image.jpg", gocv.IMReadGrayScale)
	if mat.Empty() {
		b.Fatal("failed to read source image")
	}
	defer mat.Close()

	for b.Loop() {
		s.Set("testkey", &mat)
	}
}
