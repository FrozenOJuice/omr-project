package handler

import (
	"context"
	"crypto/sha512"
	"encoding/json"
	"fmt"
	"image"
	"io"
	"net/http"
	"os"

	"ubco-team15/omr/internal/database"
	"ubco-team15/omr/internal/database/sqlc"
	"ubco-team15/omr/internal/fs"
	"ubco-team15/omr/internal/httpserver/dto"

	"github.com/google/uuid"
	"gocv.io/x/gocv"
)

// A interface that presents all resources an HTTP handler should have access
// to.
type ServerResources interface {
	// Closes all connections.
	Close() error

	// Saves a marking template and returns the new ID for it.
	SaveMarkingTemplate(tmpl *dto.MarkingTemplate) (string, error)

	// Loads a marking template and returns the new ID for it.
	LoadMarkingTemplate(id string) (*dto.MarkingTemplate, error)

	// Deletes a marking template. Redundant calls are safe.
	DeleteMarkingTemplate(id string)

	// Saves a preprocessing template and returns the new ID for it.
	SavePreprocessingTemplate(tmpl *dto.PreprocessingTemplate) (string, error)

	// Loads a preprocessing template and returns the ID for it.
	LoadPreprocessingTemplate(id string) (*dto.PreprocessingTemplate, error)

	// Deletes a preprocessing template and its anchors. Redundant calls are
	// safe.
	DeletePreprocessingTemplate(id string)

	// Loads anchor matrices. To get the i-th page's j-th anchor, you would
	// index [i][j] from the returned slice.
	LoadAnchors(templateId string) ([][]*gocv.Mat, error)

	// Saves the given anchor matrix.
	SaveAnchor(
		anchors *gocv.Mat,
		templateId string,
		pageIdx, anchorIdx int,
	) error

	// Saves a preprocessed scan via two slices of matrices: the first
	// represents the binarized images we will use for marking, and the second
	// represents the grayscaled image we will use to make human-readable
	// snippets. The template ID refers to the preprocessing template used to
	// produce these scans.
	SaveScan(
		pages []*gocv.Mat,
		pagePictures []*gocv.Mat,
		templateId string,
	) (string, error)

	// Loads a preprocessed scan's binarized pages.
	LoadScan(scanId string) ([]*gocv.Mat, error)

	// Deletes a scan and its pages. Redundant calls are safe.
	DeleteScan(scanId string)

	// Loads a picture from a scan. The "picture" of a scan is the version that
	// is maintained for human viewers. (Preprocessing leaves the main scan
	// a little ugly).
	LoadScanPicture(scanId string, pageIdx int) (image.Image, error)

	// Opens a scan picture for reading.
	OpenScanPicture(scanId string, pageIdx int) (io.ReadCloser, error)

	// Returns the total number of pictures stored and the number of bytes they
	// collectively occupy.
	CountPictures() (int, uint64)

	// Returns the total number of matrices stored and the number of bytes they
	// collectively occupy.
	CountMats() (int, uint64)

	// Returns the number of bytes used by the database.
	DBSize() uint64

	// Returns true if and only if the request's headers include the proper
	// administrator key.
	CheckAdminKey(r *http.Request) bool

	// Sets the admin key.
	SetAdminKey(key string)
}

//
// Below, we implement the interface using local resources.
//

type localResources struct {
	DBCnx  io.Closer
	DB     database.Querier
	DBPath string
	Images fs.ImageStore
	Mats   fs.MatStore
	key    [64]byte
}

var _ ServerResources = (*localResources)(nil)

// An implementation of ServerResources that uses a default SQLite database and
// stores files locally. All data (i.e., the SQLite file and the root directory
// for stored files) will be stored in the specified root.
func NewLocalResources(rootDir string) (*localResources, error) {

	if err := os.MkdirAll(rootDir, 0755); err != nil {
		return nil, err
	}

	dbPath := rootDir + "/database.sqlite3"
	db, cnx, err := database.Connect(dbPath)
	if err != nil {
		return nil, err
	}

	images, err := fs.NewLocalImageStore(rootDir + "/images")
	if err != nil {
		return nil, err
	}

	mats, err := fs.NewLocalMatStore(rootDir + "/matrices")
	if err != nil {
		return nil, err
	}

	res := &localResources{
		DBCnx:  cnx,
		DB:     db,
		DBPath: dbPath,
		Images: images,
		Mats:   mats,
	}
	return res, nil
}

func (s *localResources) Close() error {
	return s.DBCnx.Close()
}

//
// Marking Templates
//
// Marking templates are just big JSON things. We could compress the JSON if we
// want to, but it would be more efficient to create the proper tables for them
// instead of storing the raw JSON as bytes. However, we will put that off
// until we're sure that the template shape won't change dramatically.
//

func (s *localResources) SaveMarkingTemplate(
	tmpl *dto.MarkingTemplate,
) (string, error) {

	buf, err := json.Marshal(tmpl)
	if err != nil {
		return "", err
	}

	id := uuid.New()

	err = s.DB.CreateMarkingTemplate(
		context.Background(),
		sqlc.CreateMarkingTemplateParams{
			ID:   id.String(),
			Json: buf,
		},
	)
	if err != nil {
		return "", err
	}

	return id.String(), nil
}

func (s *localResources) LoadMarkingTemplate(
	id string,
) (*dto.MarkingTemplate, error) {

	record, err := s.DB.GetMarkingTemplate(context.Background(), id)
	if err != nil {
		return nil, err
	}

	tmpl := &dto.MarkingTemplate{}
	if err := json.Unmarshal(record.Json, tmpl); err != nil {
		return nil, err
	}

	return tmpl, nil
}

func (s *localResources) DeleteMarkingTemplate(id string) {
	s.DB.DeleteMarkingTemplate(context.Background(), id)
}

//
// Preprocessing Templates
//
// Unlike marking templates, preprocessing templates are a lot more modest in
// size. We just store the uncompressed JSON.
//

func (s *localResources) SavePreprocessingTemplate(
	tmpl *dto.PreprocessingTemplate,
) (string, error) {

	id := uuid.New()
	jsonStr, err := json.Marshal(tmpl)
	if err != nil {
		return "", err
	}

	err = s.DB.CreatePreprocessingTemplate(
		context.Background(),
		sqlc.CreatePreprocessingTemplateParams{
			ID:   id.String(),
			Json: string(jsonStr),
		},
	)
	if err != nil {
		return "", err
	}

	return id.String(), nil
}

func (s *localResources) LoadPreprocessingTemplate(
	id string,
) (*dto.PreprocessingTemplate, error) {

	record, err := s.DB.GetPreprocessingTemplate(context.Background(), id)
	if err != nil {
		return nil, err
	}

	tmpl := &dto.PreprocessingTemplate{}
	if err := json.Unmarshal([]byte(record.Json), tmpl); err != nil {
		return nil, err
	}

	return tmpl, nil
}

func (s *localResources) DeletePreprocessingTemplate(id string) {
	s.DB.DeletePreprocessingTemplate(context.Background(), id)
	anchors, _ := s.DB.GetAnchorsForTemplate(context.Background(), id)
	for _, anchor := range anchors {
		s.Mats.Delete(anchor.ID)
	}
	s.DB.DeleteAnchorsForTemplate(context.Background(), id)
}

//
// Anchors
//
// Anchors are stored as matrices. These methods just straightforwardly call
// the MatStore methods.
//

func (s *localResources) SaveAnchor(
	mat *gocv.Mat,
	templateId string,
	pageIdx, anchorIdx int,
) error {

	id := uuid.New().String() + ".m4t"
	if err := s.Mats.Set(id, mat); err != nil {
		return err
	}

	err := s.DB.CreateAnchor(
		context.Background(),
		sqlc.CreateAnchorParams{
			ID:          id,
			TemplateID:  templateId,
			PageIndex:   int64(pageIdx),
			AnchorIndex: int64(anchorIdx),
		},
	)
	if err != nil {
		s.Mats.Delete(id)
		return err
	}

	return nil
}

func (s *localResources) LoadAnchors(
	templateId string,
) ([][]*gocv.Mat, error) {

	anchorRecords, err := s.DB.GetAnchorsForTemplate(
		context.Background(),
		templateId,
	)
	if err != nil {
		return nil, err
	}
	if len(anchorRecords) == 0 {
		return nil, fmt.Errorf("no anchors found for template %s", templateId)
	}

	mats := make([][]*gocv.Mat, 0, 2)
	for _, record := range anchorRecords {

		// The query will sort the anchors by ascending page index and then
		// anchor index. That's the reason this loop works as intended.

		anchor, err := s.Mats.Get(record.ID)
		if err != nil {
			return nil, err
		}

		if record.AnchorIndex == 0 {
			mats = append(mats, make([]*gocv.Mat, 0, 4))
		}
		mats[record.PageIndex] = append(mats[record.PageIndex], anchor)

	}

	return mats, nil
}

//
// Scans
//
// Scans used for processing are stored as matrices. Each scan also needs a
// matching human-viewable picture for producing snippets.
//

func (s *localResources) SaveScan(
	pages []*gocv.Mat,
	pagePictures []*gocv.Mat,
	templateId string,
) (string, error) {

	scanId := uuid.New().String()
	err := s.DB.CreateScan(context.Background(), sqlc.CreateScanParams{
		ID:                      scanId,
		PreprocessingTemplateID: templateId,
	})
	if err != nil {
		return "", err
	}

	for i := range pages {

		pageId := uuid.New().String() + ".m4t"
		if err := s.Mats.Set(pageId, pages[i]); err != nil {
			return "", err
		}

		pictureId := uuid.New().String() + fs.ImgFileExt
		pictureBuf, err := gocv.IMEncode(fs.OpenCVImgExt, *pagePictures[i])
		if err != nil {
			return "", err
		}
		defer pictureBuf.Close()

		err = s.Images.SetBytes(pictureId, pictureBuf.GetBytes())
		if err != nil {
			return "", err
		}

		err = s.DB.CreateScanPage(
			context.Background(),
			sqlc.CreateScanPageParams{
				ID:         pageId,
				PictureKey: pictureId,
				PageIndex:  int64(i),
				ScanID:     scanId,
			},
		)
		if err != nil {
			return "", err
		}
	}

	return scanId, nil
}

func (s *localResources) LoadScan(scanId string) ([]*gocv.Mat, error) {
	records, err := s.DB.GetPagesForScan(context.Background(), scanId)
	if err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, fmt.Errorf("no pages found for scan %s", scanId)
	}

	mats := make([]*gocv.Mat, len(records))
	for i, record := range records {
		mat, err := s.Mats.Get(record.ID)
		if err != nil {
			return nil, err
		}
		mats[i] = mat
	}

	return mats, nil
}

func (s *localResources) DeleteScan(id string) {
	s.DB.DeleteScan(context.Background(), id)
	pages, _ := s.DB.GetPagesForScan(context.Background(), id)
	for _, page := range pages {
		s.Images.Delete(page.PictureKey)
		s.Mats.Delete(page.ID)
	}
	s.DB.DeletePagesForScan(context.Background(), id)
}

func (s *localResources) LoadScanPicture(
	scanId string,
	pageIdx int,
) (image.Image, error) {

	page, err := s.DB.GetScanPage(
		context.Background(),
		sqlc.GetScanPageParams{
			ScanID:    scanId,
			PageIndex: int64(pageIdx),
		},
	)
	if err != nil {
		return nil, err
	}

	img, err := s.Images.Get(page.PictureKey)
	if err != nil {
		return nil, err
	}

	return img, nil
}

func (s *localResources) OpenScanPicture(
	scanId string,
	pageIdx int,
) (io.ReadCloser, error) {

	page, err := s.DB.GetScanPage(
		context.Background(),
		sqlc.GetScanPageParams{
			ScanID:    scanId,
			PageIndex: int64(pageIdx),
		},
	)
	if err != nil {
		return nil, err
	}

	img, err := s.Images.Open(page.PictureKey)
	if err != nil {
		return nil, err
	}

	return img, nil

}

func (s *localResources) CountPictures() (int, uint64) {
	return s.Images.Count()
}

func (s *localResources) CountMats() (int, uint64) {
	return s.Mats.Count()
}

func (s *localResources) DBSize() uint64 {
	info, err := os.Stat(s.DBPath)
	if err != nil {
		return 0
	}

	return uint64(info.Size())
}

func (s *localResources) SetAdminKey(key string) {
	s.key = sha512.Sum512([]byte(key))
}

func (s *localResources) CheckAdminKey(r *http.Request) bool {
	k := r.Header.Get("OMR-Admin-Key")
	if k == "" {
		return false
	}

	return s.key == sha512.Sum512([]byte(k))
}
