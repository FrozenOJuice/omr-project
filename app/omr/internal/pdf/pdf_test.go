package pdf

import (
	"bytes"
	"embed"
	"fmt"
	"image"
	"image/draw"
	"image/png"
	"reflect"
	"testing"

	"github.com/gen2brain/go-fitz"
	"gocv.io/x/gocv"
)

//go:embed testdata/*
var testData embed.FS

func TestRenderPageBlocks_OK(t *testing.T) {

	// The large sample PDF has 88 pages.
	buf, err := testData.ReadFile("testdata/sample_large.pdf")
	if err != nil {
		t.Fatal(err)
	}

	batches, nBatches, err := RenderPageBlocks(
		bytes.NewReader(buf),
		74,
		2,
		0,
	)
	if err != nil {
		t.Fatal(err)
	}

	if nBatches != 88/2 {
		t.Fatalf(
			"pdf had %d pages but only %d %d-page batches were prepared",
			88, nBatches, 2,
		)
	}

	nBatchesRendered := 0
	for batch := range batches {
		nBatchesRendered++

		if batch.Error != nil {
			t.Fatal(batch.Error)
		}

		// Ensure that each page's matrix is a well-formed image.
		for _, page := range batch.Pages {
			_, err := gocv.IMEncode(gocv.PNGFileExt, *page)
			if err != nil {
				t.Fatal(err)
			}
		}
	}

	// Ensure that each page was rendered.
	if nBatchesRendered != 88/2 {
		t.Fatalf(
			"pdf had %d pages but only %d %d-page batches were rendered",
			88, nBatchesRendered, 2,
		)
	}
}

func TestRenderPageBlocks_MalformedData(t *testing.T) {

	//
	// This test checks how the renderer handles non-PDF data being passed to
	// it.
	//

	// Check a text file. This should not be parseable at all by the PDF
	// renderer.
	buf, err := testData.ReadFile("testdata/not_a_pdf.txt")
	if err != nil {
		t.Fatal(err)
	}

	_, _, err = RenderPageBlocks(
		bytes.NewReader(buf),
		74,
		2,
		0,
	)
	if err != ErrMalformedPdf {
		t.Fatal("expected ErrMalformedPdf error")
	}

	// Check an image file. The MagickWand library is able to handle all kinds
	// of images, so it's conceivable that it would fail silently. We need to
	// ensure that it doesn't.
	buf, err = testData.ReadFile("testdata/not_a_pdf.jpg")
	if err != nil {
		t.Fatal(err)
	}

	_, _, err = RenderPageBlocks(
		bytes.NewReader(buf),
		74,
		2,
		0,
	)
	if err != ErrMalformedPdf {
		t.Fatal("expected ErrMalformedPdf error")
	}
}

func TestRenderPageBlocks_PageMismatch(t *testing.T) {
	// The large sample PDF has 88 pages.
	buf, err := testData.ReadFile("testdata/sample_large.pdf")
	if err != nil {
		t.Fatal(err)
	}

	// 3 does not divide 88, so we expect this to err.
	_, _, err = RenderPageBlocks(
		bytes.NewReader(buf),
		74,
		3,
		0,
	)
	if err != ErrPageCountMismatch {
		t.Fatalf("expected ErrPageCountMismatch, got %s", err.Error())
	}
}

//
// Test the helper functions.
//

func TestBlockPartition(t *testing.T) {
	tests := []struct {
		name            string
		n               uint
		blockSize       uint
		numberOfSubsets uint
		want            []blockedSubset
		err             error
	}{
		{
			name:            "single subset",
			n:               12,
			blockSize:       4,
			numberOfSubsets: 1,
			want: []blockedSubset{
				{
					from: 1,
					thru: 12,
					blocks: []block{
						{from: 1, thru: 4},
						{from: 5, thru: 8},
						{from: 9, thru: 12},
					},
				},
			},
		},
		{
			name:            "two equal subsets",
			n:               12,
			blockSize:       2,
			numberOfSubsets: 2,
			want: []blockedSubset{
				{
					from: 1,
					thru: 6,
					blocks: []block{
						{from: 1, thru: 2},
						{from: 3, thru: 4},
						{from: 5, thru: 6},
					},
				},
				{
					from: 7,
					thru: 12,
					blocks: []block{
						{from: 7, thru: 8},
						{from: 9, thru: 10},
						{from: 11, thru: 12},
					},
				},
			},
		},
		{
			name:            "three equal subsets",
			n:               12,
			blockSize:       2,
			numberOfSubsets: 3,
			want: []blockedSubset{
				{
					from: 1,
					thru: 4,
					blocks: []block{
						{from: 1, thru: 2},
						{from: 3, thru: 4},
					},
				},
				{
					from: 5,
					thru: 8,
					blocks: []block{
						{from: 5, thru: 6},
						{from: 7, thru: 8},
					},
				},
				{
					from: 9,
					thru: 12,
					blocks: []block{
						{from: 9, thru: 10},
						{from: 11, thru: 12},
					},
				},
			},
		},
		{
			name:            "uneven subsets",
			n:               20,
			blockSize:       2,
			numberOfSubsets: 3,
			want: []blockedSubset{
				{
					from: 1,
					thru: 8,
					blocks: []block{
						{from: 1, thru: 2},
						{from: 3, thru: 4},
						{from: 5, thru: 6},
						{from: 7, thru: 8},
					},
				},
				{
					from: 9,
					thru: 14,
					blocks: []block{
						{from: 9, thru: 10},
						{from: 11, thru: 12},
						{from: 13, thru: 14},
					},
				},
				{
					from: 15,
					thru: 20,
					blocks: []block{
						{from: 15, thru: 16},
						{from: 17, thru: 18},
						{from: 19, thru: 20},
					},
				},
			},
		},
		{
			name:            "one block per subset",
			n:               12,
			blockSize:       4,
			numberOfSubsets: 3,
			want: []blockedSubset{
				{
					from:   1,
					thru:   4,
					blocks: []block{{from: 1, thru: 4}},
				},
				{
					from:   5,
					thru:   8,
					blocks: []block{{from: 5, thru: 8}},
				},
				{
					from:   9,
					thru:   12,
					blocks: []block{{from: 9, thru: 12}},
				},
			},
		},
		{
			name:            "invalid block size",
			n:               10,
			blockSize:       4,
			numberOfSubsets: 2,
			err:             ErrInvalidBlockSize,
		},
		{
			name:            "more subsets than blocks",
			n:               8,
			blockSize:       4,
			numberOfSubsets: 3,
			want: []blockedSubset{
				{
					from:   1,
					thru:   4,
					blocks: []block{{from: 1, thru: 4}},
				},
				{
					from:   5,
					thru:   8,
					blocks: []block{{from: 5, thru: 8}},
				},
			},
		},
		{
			name:            "zero pages",
			n:               0,
			blockSize:       1,
			numberOfSubsets: 3,
			want:            []blockedSubset{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := blockPartition(tt.n, tt.blockSize, tt.numberOfSubsets)

			if err != tt.err {
				t.Fatalf("expected error %v, got %v", tt.err, err)
			}

			if err != nil {
				return
			}

			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("blockPartition(%d, %d, %d) = %#v, want %#v",
					tt.n, tt.blockSize, tt.numberOfSubsets, got, tt.want)
			}
		})
	}
}

func TestRenderPages(t *testing.T) {

	f, err := testData.Open("testdata/sample_large.pdf")
	if err != nil {
		t.Fatal(err)
	}

	doc, err := fitz.NewFromReader(f)
	if err != nil {
		t.Fatal(err)
	}

	var tests = []struct {
		startIdx uint
		count    uint
		err      error
	}{
		{1, 2, nil},
		{6, 88, ErrPageOutOfBounds},
		{0, 2, nil},
		{4, 2, nil},
		{88, 0, ErrPageOutOfBounds},
	}

	for _, tt := range tests {
		name := fmt.Sprintf(
			"startIdx=%d count=%d (88 pages)",
			tt.startIdx, tt.count,
		)
		if tt.err != nil {
			name += fmt.Sprintf("; error=%s", tt.err.Error())
		}
		t.Run(name, func(t *testing.T) {
			mats, err := renderPages(doc, 74, tt.startIdx, tt.count)
			if err == nil {
				defer closeAll(mats)
			}
			if err != tt.err {
				t.Errorf("err: got %v, want %v", err, tt.err)
			}

			if err != nil {
				return
			}
			if uint(len(mats)) != tt.count {
				t.Errorf("len: got %d, want %d", len(mats), tt.count)
			}

			//
			// Uncomment the following block and create a "testoutput"
			// directory if you need to manually review the output.
			//

			// for i, mat := range mats {
			// 	gocv.IMWrite(
			// 		fmt.Sprintf(
			// 			"testoutput/render_pages_start%dcount%d_%d.png",
			// 			tt.startIdx, tt.count, i,
			// 		),
			// 		*mat,
			// 	)
			// }
		})
	}
}

func TestRgbaToGrayMat(t *testing.T) {

	f, err := testData.Open("testdata/sample_image.png")
	if err != nil {
		t.Fatal(err)
	}

	img, err := png.Decode(f)
	if err != nil {
		t.Fatal(err)
	}

	img.ColorModel()

	rgba, ok := img.(*image.RGBA)
	if !ok {
		b := img.Bounds()
		rgba = image.NewRGBA(b)
		draw.Draw(rgba, b, img, b.Min, draw.Over)
	}

	mat, err := rgbaToGrayMat(rgba)
	if err != nil {
		t.Fatal(err)
	}
	defer mat.Close()

	//
	// Uncomment the following statement and create a "testoutput" directory if
	// you need to manually review the output.
	//

	// gocv.IMWrite("testoutput/rgba_to_gray_mat_output.png", mat)
}

func TestPageSpan(t *testing.T) {
	buf, err := testData.ReadFile("testdata/sample_large.pdf")
	if err != nil {
		t.Fatal(err)
	}
	r := bytes.NewReader(buf)

	ctx, err := splittingContext(r)
	if err != nil {
		t.Fatal(err)
	}

	var tests = []struct {
		from uint
		thru uint
		err  error
	}{
		{1, 2, nil},
		{6, 88, nil},
		{0, 2, ErrPageOutOfBounds},
		{4, 2, ErrBadInput},
		{56, 102, ErrPageOutOfBounds},
	}

	for _, tt := range tests {
		name := fmt.Sprintf(
			"from=%d thru=%d (88 pages)",
			tt.from, tt.thru,
		)
		if tt.err != nil {
			name += fmt.Sprintf("; error=%s", tt.err.Error())
		}
		t.Run(name, func(t *testing.T) {
			buf := bytes.Buffer{}
			err := pageSpan(&buf, ctx, tt.from, tt.thru)
			if err != tt.err {
				t.Errorf("err: got %v, want %v", err, tt.err)
			}

			if tt.err != nil {
				return
			}
		})
	}
}
