CREATE TABLE IF NOT EXISTS marking_templates (
    id TEXT PRIMARY KEY,
    json BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS preprocessing_templates (
    id TEXT PRIMARY KEY,
    json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    page_index INT NOT NULL,
    anchor_index INT NOT NULL,
    FOREIGN KEY(template_id) REFERENCES preprocessing_templates(id)
);

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    preprocessing_template_id TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
    FOREIGN KEY(preprocessing_template_id) REFERENCES preprocessing_templates(id)
);

CREATE TABLE IF NOT EXISTS scan_pages (
    id TEXT PRIMARY KEY,
    picture_key TEXT NOT NULL,
    page_index INT NOT NULL,
    scan_id TEXT NOT NULL,
    FOREIGN KEY(scan_id) REFERENCES scans(id)
);
