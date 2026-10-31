-- name: CreateMarkingTemplate :exec
INSERT INTO
    marking_templates (id, json)
VALUES
    (?, ?);

-- name: GetMarkingTemplate :one
SELECT
    *
FROM
    marking_templates
WHERE
    id = ?;

-- name: DeleteMarkingTemplate :execrows
DELETE FROM
    marking_templates
WHERE
    id = ?;

-- name: CreatePreprocessingTemplate :exec
INSERT INTO
    preprocessing_templates (id, json)
VALUES
    (?, ?);

-- name: GetPreprocessingTemplate :one
SELECT
    *
FROM
    preprocessing_templates
WHERE
    id = ?;

-- name: DeletePreprocessingTemplate :execrows
DELETE FROM
    preprocessing_templates
WHERE
    id = ?;

-- name: CreateAnchor :exec
INSERT INTO
    anchors (
        id,
        template_id,
        page_index,
        anchor_index
    )
VALUES
    (?, ?, ?, ?);

-- name: CountAnchors :one
SELECT
    count(*)
FROM
    anchors;

-- name: GetAnchorsForTemplate :many
SELECT
    *
FROM
    anchors
WHERE
    template_id = ?
ORDER BY
    page_index ASC,
    anchor_index ASC;

-- name: GetOneAnchorForTemplate :one
SELECT
    *
FROM
    anchors
WHERE
    template_id = ?
    AND page_index = ?
    AND anchor_index = ?;

-- name: DeleteAnchorsForTemplate :execrows
DELETE FROM
    anchors
WHERE
    template_id = ?;

-- name: CreateScan :exec
INSERT INTO
    scans (id, preprocessing_template_id)
VALUES
    (?, ?);

-- name: CreateScanPage :exec
INSERT INTO
    scan_pages (id, picture_key, page_index, scan_id)
VALUES
    (?, ?, ?, ?);

-- name: CountScans :one
SELECT
    count(*)
FROM
    scans;

-- name: DeleteScan :execrows
DELETE FROM
    scans
WHERE
    id = ?;

-- name: GetScanPage :one
SELECT 
    *
FROM
    scan_pages
WHERE
    scan_id = ? AND
    page_index = ?
LIMIT 1;

-- name: GetPagesForScan :many
SELECT 
    *
FROM
    scan_pages
WHERE
    scan_id = ?
ORDER BY
    page_index ASC;

-- name: DeletePagesForScan :execrows
DELETE FROM
    scan_pages
WHERE
    scan_id = ?;
