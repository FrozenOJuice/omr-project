# Multipart scan uploads

## Current implementation

The frontend asks FastAPI for presigned multipart URLs, uploads chunks directly to
Garage, then finalizes the PDF through FastAPI. The application records pending
scans and starts the OMR preprocessing/grading pipeline in the background.

| Operation | Current API contract |
| --- | --- |
| Initiate | `POST /api/scans/initiate`: `exam_id`, `exam_template_id`, `filename`, `total_chunks`; returns `upload_id`, `storage_path`, and presigned part URLs |
| Chunk limit | The router rejects more than 39 chunks |
| Finalize PDF | `POST /api/scans/finalize-pdf`: same exam/template IDs, `upload_id`, `storage_path`, and `parts` containing `PartNumber` and `ETag` |
| Small direct upload | `POST /api/scans/pdf`, multipart form with exam/template IDs and a PDF file; the router limits this body to 200,000,000 file bytes |
| Progress | `GET /api/scans/{scan_id}/job-status` for the pending scan's job |
| Role guard | Staff (professor or administrator) on the operations above |

Sources: [scan router](../../app/backend/routers/scan_router.py),
[schemas](../../app/backend/schemas/scan_schema.py),
[scan service](../../app/backend/services/scans.py).
The existing role checks do not establish course-level authorization; see the
[hosting limitations](../portfolio/publication.md#hosting-is-a-separate-decision).
No endpoint behavior was changed for the portfolio.

## Historical upload-design draft

The following original draft is retained as capstone design evidence. Its endpoint
names, chunk limit, authorization notes, and request examples are superseded by
the current implementation summary above.

---

## Large File Upload Architecture (Multipart Chunked Scans)

To support large files without exhausting backend memory, and faster uploads, the system uses an Multipart Upload workflow via Garage Storage. The frontend streams binary chunks directly to the storage cluster using pre-signed URLs, bypassing the FastAPI backend gateway.

### Sequence Flow

1. **Frontend → Backend (`POST /scans/initiate`):** Sends `filename` and `total_chunks`.
2. **Backend → Storage:** Requests a unique upload session tracking ID.
3. **Backend → Frontend:** Returns the `upload_id`, `storage_path`, and a list of pre-signed URLs (one for each chunk index).
4. **Frontend → Storage:** Executes direct HTTP `PUT` requests to upload each raw binary chunk.
5. **Storage → Frontend:** Confirms each chunk delivery and returns a unique `ETag` receipt string in the response headers.
6. **Frontend → Backend (`POST /scans/finalize`):** Sends the metadata along with the ordered list of `part_number` and `etag` values.
7. **Backend → Storage:** Orders the assembly/stitching of the chunks into the final PDF.
8. **Backend → DB:** Registers the completed `Scan` metadata inside PostgreSQL.

### API Contract Summaries

#### 1. Initiate Session
* **Endpoint:** `POST /api/scans/initiate`
* **Role Guard:** Currently any, will be updated
* **Max Chunks:** 100
* **Request:** `{"exam_template_id": "UUID", "filename": "string", "total_chunks": int}`
* **Response:** `{"upload_id": "string", "storage_path": "string", "urls": [{"part_number": int, "url": "string"}]}`

#### 2. Finalize Upload
* **Endpoint:** `POST /api/scans/finalize`
* **Role Guard:** Admin, Professor
* **Request:**
```json
{
  "exam_template_id": "UUID",
  "upload_id": "string",
  "storage_path": "string",
  "page_count": int, #pages in pdf
  "parts": [
    { "part_number": 1, "etag": "\"string\"" },
    { "part_number": 2, "etag": "\"string\"" }
  ]
}
```
