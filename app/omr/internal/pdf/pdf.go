package pdf

import (
	"errors"
	"image"
	"io"
	"os"
	"runtime"
	"sync/atomic"

	"github.com/gen2brain/go-fitz"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
	"gocv.io/x/gocv"
)

const (
	MaxDpi              uint = 300
	MaxConcurrentBlocks uint = 6
)

var (
	ErrBadInput          = errors.New("pdf: nonsensical input. Likely a programmer error")
	ErrPageOutOfBounds   = errors.New("pdf: page index is out of bounds for the document")
	ErrMalformedPdf      = errors.New("pdf: the given file does not form a PDF")
	ErrPageCountMismatch = errors.New("pdf: the given PDF page count is not a multiple of the block size")
	ErrInvalidBlockSize  = errors.New("pdf: the given block size does not divide the given n")
)

type PageBlock struct {
	Pages []*gocv.Mat
	From  uint
	Thru  uint
	Error error
}

func (p *PageBlock) Close() {
	for i := range p.Pages {
		p.Pages[i].Close()
	}
	p.Pages = nil
}

func RenderPageBlocks(
	r io.ReadSeeker,
	dpi uint,
	blockSize uint,
	allottedThreads uint,
) (chan PageBlock, uint, error) {

	dpi = min(MaxDpi, dpi)

	if allottedThreads == 0 {
		allottedThreads = min(MaxConcurrentBlocks, uint(runtime.GOMAXPROCS(0))/2)
	}

	allottedThreads = min(MaxConcurrentBlocks, allottedThreads)

	// The number of allotted threads should be scaled down when the block size
	// is above 2. Most exams won't be more than two pages, but the possibility
	// still needs to be addressed because it can spike the memory if we hold
	// a bunch of large blocks simultaneously. (It's also worth mentioning that
	// this equation can return a value greater than MaxConcurrentBlocks when
	// blocks are 1-page, but that's fine.)
	allottedThreads = uint(max(1, int(allottedThreads)+2-int(blockSize)))

	docs, err := blockPartitionPdf(r, blockSize, allottedThreads)
	if err != nil {
		return nil, 0, err
	}

	numBlocks := uint(0)
	for _, doc := range docs {
		numBlocks += uint(len(doc.subset.blocks))
	}

	threadCount := atomic.Int32{}
	ch := make(chan PageBlock)

	for i := range docs {
		go func() {
			threadCount.Add(1)

			doc := docs[i]
			defer doc.close()

			for i, block := range doc.subset.blocks {
				startIdx := uint(i) * blockSize
				mats, err := renderPages(doc.doc, dpi, startIdx, blockSize)
				if err != nil {
					ch <- PageBlock{
						Pages: nil,
						From:  block.from,
						Thru:  block.thru,
						Error: err,
					}
					continue
				}

				ch <- PageBlock{
					Pages: mats,
					From:  block.from,
					Thru:  block.thru,
					Error: nil,
				}
			}

			if threadCount.Add(-1) == 0 {
				close(ch)
			}
		}()
	}

	return ch, numBlocks, nil
}

type blockedSubdoc struct {
	subset blockedSubset
	doc    *fitz.Document
	file   *os.File
}

func (b *blockedSubdoc) close() {
	b.doc.Close()
	b.file.Close()
	os.Remove(b.file.Name())
}

func blockPartitionPdf(
	pdf io.ReadSeeker,
	blockSize,
	numSubsets uint,
) ([]blockedSubdoc, error) {
	ctx, err := splittingContext(pdf)
	if err != nil {
		return nil, ErrMalformedPdf
	}

	subsets, err := blockPartition(uint(ctx.PageCount), blockSize, numSubsets)
	if err != nil {
		return nil, ErrPageCountMismatch
	}

	subDocs := make([]blockedSubdoc, 0, len(subsets))
	for _, subset := range subsets {

		f, err := os.CreateTemp("", "tmp_pdf_subset_*.pdf")
		if err != nil {
			for j := range subDocs {
				subDocs[j].close()
			}
			return nil, err
		}

		err = pageSpan(f, ctx, subset.from, subset.thru)
		if err != nil {
			f.Close()
			os.Remove(f.Name())
			for j := range subDocs {
				subDocs[j].close()
			}
			return nil, err
		}

		doc, err := fitz.New(f.Name())
		if err != nil {
			f.Close()
			os.Remove(f.Name())
			for j := range subDocs {
				subDocs[j].close()
			}
			return nil, err
		}

		subDocs = append(subDocs, blockedSubdoc{
			subset: subset,
			doc:    doc,
			file:   f,
		})
	}

	return subDocs, nil
}

// Represents a discrete piece of a region. The boundaries are 1-based and
// inclusive.
type block struct {
	from uint
	thru uint
}

type blockedSubset struct {
	from   uint
	thru   uint
	blocks []block
}

// Returns a set of boundaries which form a roughly-even partition of the
// numbers 1 through n, divided into blocks. All blocks will be whole. I.e., if
// the block size is 4, then all subsets will have a total size that is a
// multiple of 4.
//
// The number of subsets is an upper bound. Empty subsets will be omitted from
// the returned slice.
//
// If the block size does not divide the given n, then a partitioning is
// impossible and [ErrInvalidBlockSize] is returned.
func blockPartition(n, blockSize, numSubsets uint) ([]blockedSubset, error) {
	if n%blockSize != 0 {
		return nil, ErrInvalidBlockSize
	}

	numBlocks := n / blockSize
	numSubsets = min(numBlocks, numSubsets)
	blocksPerRegion := make([]uint, numSubsets)
	idx := uint(0)
	for numBlocks > 0 {
		numBlocks--
		blocksPerRegion[idx]++

		idx += 1
		idx %= numSubsets
	}

	regions := make([]blockedSubset, numSubsets)
	from := uint(1)
	for i, blocks := range blocksPerRegion {
		regions[i] = blockedSubset{
			blocks: make([]block, blocks),
		}
		regions[i].from = from
		for j := range blocks {
			thru := from + blockSize - 1
			regions[i].blocks[j].from = from
			regions[i].blocks[j].thru = thru
			from = thru + 1
		}
		regions[i].thru = from - 1
	}

	return regions, nil
}

// Renders a specific number of pages from the given document beginning from
// the start index.
//
// If an error is returned, it will [ErrPageOutOfBounds] or an unnamed error
// from GoCV or Fitz.
func renderPages(
	doc *fitz.Document,
	dpi,
	startIdx,
	count uint,
) ([]*gocv.Mat, error) {

	if startIdx+count > uint(doc.NumPage()) || startIdx == uint(doc.NumPage()) {
		return nil, ErrPageOutOfBounds
	}

	mats := make([]*gocv.Mat, 0, count)

	for i := startIdx; i < startIdx+count; i++ {

		img, err := doc.ImageDPI(int(i), float64(dpi))
		if err != nil {
			closeAll(mats)
			return nil, err
		}
		mat, err := rgbaToGrayMat(img)
		if err != nil {
			closeAll(mats)
			return nil, err
		}

		mats = append(mats, &mat)
	}

	return mats, nil
}

// Converts an RGBA image into a grayscale OpenCV matrix.
func rgbaToGrayMat(img *image.RGBA) (gocv.Mat, error) {

	w := img.Bounds().Dx()
	h := img.Bounds().Dy()

	bytes := make([]byte, w*h)

	for x := range w {
		for y := range h {

			//
			// This luminosity formula is copied from the Go standard library.
			// <https://cs.opensource.google/go/go/+/master:src/image/color/color.go;l=244>
			//

			pixel := img.At(x, y)
			r, g, b, _ := pixel.RGBA()
			lum := (19595*r + 38470*g + 7471*b + 1<<15) >> 24
			bytes[x+y*w] = byte(lum)
		}
	}

	return gocv.NewMatFromBytes(h, w, gocv.MatTypeCV8UC1, bytes)
}

// Closes all non-nil matrices in the given slice.
func closeAll(mats []*gocv.Mat) {
	for _, m := range mats {
		if m != nil {
			m.Close()
		}
	}
}

// Prepares a pdfcpu context for PDF splitting.
//
// If an error is returned, it will be [ErrMalformedPdf].
func splittingContext(r io.ReadSeeker) (*model.Context, error) {

	conf := model.NewDefaultConfiguration()
	conf.Cmd = model.SPLIT

	ctx, err := api.ReadValidateAndOptimize(r, conf)
	if err != nil {
		return nil, ErrMalformedPdf
	}

	return ctx, nil
}

// A reimplementation of pdfcpu's unexported "pageSpan" function. The "from"
// and "thru" values are 1-based page numbers, and the bounds are inclusive.
//
// If an error is returned, it will be [ErrPageOutOfBounds], [ErrBadInput]
// (when from > thru), or an unnamed error from pdfcpu.
func pageSpan(
	dst io.Writer,
	ctx *model.Context,
	from, thru uint,
) error {
	if from < 1 || thru > uint(ctx.PageCount) {
		return ErrPageOutOfBounds
	}

	if from > thru {
		return ErrBadInput
	}

	ctxNew, err := pdfcpu.ExtractPages(
		ctx,
		api.PagesForPageRange(int(from), int(thru)),
		false,
	)
	if err != nil {
		return nil
	}

	if err := api.WriteContext(ctxNew, dst); err != nil {
		return err
	}

	ctxNew.Write.Fp.Close()
	return nil
}
