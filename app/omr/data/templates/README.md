# OMR Templates

A form is described by two JSON files: a **scan template** that tells the preprocessor how to correct perspective, and a **mark template** that tells the marker where each answer bubble is located.

Multi-page exams (e.g. a front page for answers and a back page for student information) are supported by both template types via a `pages` array. Pass one image file per page to the CLI commands; the images are matched to pages in order.

## Usage

```
# Preprocess only (saves binary images for later marking)
omr preprocess <scan-template> <page1.jpg> [<page2.jpg>...] --output preprocessed

# Mark only (requires preprocessed binary images)
omr mark <mark-template> <page1.png> [<page2.png>...]

# Preprocess and mark in one step
omr scan <scan-template> <mark-template> <page1.jpg> [<page2.jpg>...]
```

## Example Directory Structure

```
my_form/
├── scan.json
├── mark.json
└── anchors/
    ├── logo.jpg
    ├── footer.jpg
    └── info.jpg
```

Anchor image paths in the scan template are resolved relative to the JSON file's location.

---

## Scan Template

Controls perspective correction and binarization. Pass this to `preprocess` or `scan`.

### Top-level fields

| Field    | Type   | Description |
|----------|--------|-------------|
| `width`  | int    | Output image width in pixels after warping (shared across all pages) |
| `height` | int    | Output image height in pixels after warping (shared across all pages) |
| `config` | object | Preprocessing parameters (shared across all pages, see below) |
| `pages`  | array  | One entry per exam page; each entry contains that page's `anchors` array |

### Page (scan)

| Field     | Type  | Description |
|-----------|-------|-------------|
| `anchors` | array | At least 3 anchor definitions for this page (see below) |

### Anchor

Each anchor is a distinctive region of the sheet used to compute the affine transform. All coordinates are in output (`width` × `height`) space. With 3 anchors the transform is exact; with 4+ it uses a least-squares fit, which is more robust against individual matching errors. Spread anchors around all four corners of the page content area for best accuracy. Use a different set of anchors for each page so the layout identifies which side is up.

| Field    | Type   | Description |
|----------|--------|-------------|
| `path`   | string | Path to a cropped image of the anchor region, relative to the JSON file |
| `center` | Point  | Where the centre of this anchor should land in the output (`{"X": n, "Y": n}`) |
| `roi`    | Rect   | Search region in output space (`{"Min": {"X":n,"Y":n}, "Max": {"X":n,"Y":n}}`). Keep it generous but targeted. |

Anchor images should be cropped from a clean, straight scan of the sheet. They are binarized automatically at load time.

### Scan Config

| Field                 | Type    | Default | Description |
|-----------------------|---------|---------|-------------|
| `blurSize`            | int     | —       | Gaussian blur kernel size, must be odd. Increase for noisier scans. |
| `morphCloseSize`      | int     | —       | Morphological close kernel size. Helps fill sparse pencil marks. |
| `minAnchorConfidence` | float32 | —       | Minimum template-match score (0.0–1.0). Raise if anchors produce false positives. |
| `adaptiveBlockSize`   | int     | `91`    | Neighbourhood size (pixels, must be odd) for adaptive thresholding. Larger values use a wider local region to compute the threshold; recommended starting point is roughly 3× the bubble diameter at scan resolution. |
| `adaptiveC`           | float32 | `-15`   | Constant subtracted from the local mean before thresholding (`T = mean − C`). Positive values lower the threshold, giving cleaner ink/paper separation on high-contrast flatbed scans. Negative values raise the threshold, which can help detect lighter pencil marks but risks misclassifying clean white areas as ink. |

---

## Mark Template

Defines question and bubble locations. Pass this to `mark` or `scan`.

### Top-level fields

| Field    | Type   | Description |
|----------|--------|-------------|
| `config` | object | Marking parameters, shared across all pages (see below) |
| `pages`  | array  | One entry per exam page; each entry contains that page's `questions` array |

### Page (mark)

| Field       | Type  | Description |
|-------------|-------|-------------|
| `questions` | array | Ordered list of questions and their bubble locations for this page (see below) |

### Mark Config

| Field           | Type    | Default | Description |
|-----------------|---------|---------|-------------|
| `fillThreshold` | float64 | 0.25    | Minimum gap between the selected bubble's fill and the next-best to count as a selection (0.0–1.0). |
| `bubbleInset`   | float64 | 0.75    | Fraction of the bubble radius sampled. Values below 1.0 exclude the printed border ring from the measurement. |
| `flagThreshold` | float64 | 0.5     | Minimum confidence below which an answer is flagged for manual review. Set to 0.0 to disable. |
| `searchRadius`  | int     | 0       | Per-axis pixel search window around each bubble's template position. The maximum fill found across the (2r+1)² candidate centres is used. Set to 3–5 to tolerate small printer/scanner misalignment. |

### Question

Question IDs use a prefix convention to identify the field type:

| Prefix | Meaning | Example |
|--------|---------|---------|
| `Q#`   | Exam answer question | `Q1`, `Q42` |
| `V#`   | Exam version selector | `V1` |
| `L#`   | Last name character column | `L1`–`L15` |
| `F#`   | First name character column | `F1`–`F10` |
| `I#`   | Student ID digit column | `I1`–`I8` |

| Field          | Type   | Description |
|----------------|--------|-------------|
| `id`           | string | Identifier used in the output report (e.g. `"Q1"`) |
| `type`         | string | `"single"` (default) flags multiple selections; `"multi"` allows them |
| `bubbleWidth`  | int    | Width of every bubble in this question, in output-space pixels |
| `bubbleHeight` | int    | Height of every bubble in this question, in output-space pixels |
| `options`      | array  | Ordered list of bubbles (see below) |

### Bubble

| Field   | Type   | Description |
|---------|--------|-------------|
| `label` | string | Answer label shown in the output report (e.g. `"A"`) |
| `x`     | int    | X coordinate of the bubble centre in output-space pixels |
| `y`     | int    | Y coordinate of the bubble centre in output-space pixels |
