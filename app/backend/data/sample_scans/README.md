# Capstone-course manual-upload test scans

40 pre-generated, scanner-degraded PDFs for manually testing the scan-upload
flow against the `COSC 499 - Capstone Project` course created by
`make dev-seed` (see `../../seed.py`).

## Why these exist

`dev-seed` seeds a large (~200-student) roster but
**seeds no scans or grades at all** for either exam — unlike every other
seeded exam in this project. That's intentional: a fabricated "completed"
row for all ~200 students would bury the handful of real, manually-uploaded
scans this directory exists to test. The first 20 students (student numbers
`90000000` through `90000019`) get a real, filled bubble
sheet here instead, one on each exam template (`Capstone Midterm` and
`Capstone Final Exam`), so a tester can manually upload a real scan and see it
match a real roster entry, standing out clearly against an otherwise-empty
grade sheet — the same idea as the 3 physically hand-filled sheets for Joe
Blow/Mama/Shmoe in the main demo course, but generated and varied across the
conditions below instead of printed and hand-scanned. The other ~180
students exist purely as roster filler for scale/pagination testing and have
no associated scan, fixture, or grade of any kind.

Each student's condition is **randomized** (DPI, mark darkness, page order)
under a fixed seed, generated once by
[`scripts/generate_extended_test_scans.py`](../../scripts/generate_extended_test_scans.py)
and committed here — not regenerated on every `dev-seed` run. Only
re-run that script if the COSC 499 seed identity changes (e.g. the exam
templates in `seed.py` are edited); otherwise these fixtures stay valid
indefinitely.

`showcase00` is a fixed **baseline control** (216 DPI, full darkness, normal
page order) — upload it first to confirm the pipeline works before trying
the randomized ones.

## How to use

1. Run `make dev-seed` (if you haven't already).
2. Log in as `test.prof@example.com` / `Password123!`, open
   `COSC 499 - Capstone Project`.
3. Upload any file below through the normal scan-upload flow, against the
   matching exam (`custom_*` → Capstone Midterm, `ubc_*` → Capstone Final
   Exam).
4. It should match the roster entry named in the table below by student ID.
   Some vary the DPI or swap page order on purpose. Review warnings where
   present; swapped pairs exercise the pipeline's automatic correction path.

## Fixture index

Every student below has two files: `custom_<slug>.pdf` and
`ubc_<slug>.pdf`, both rendered under the same condition (same DPI/darkness/
page order) so one identity = one condition across both exam formats.

| # | Name | Email | Student ID | DPI | Darkness | Page order | Notes |
|---|------|-------|------------|-----|----------|------------|-------|
| 00 | Olivia Nguyen | olivia.nguyen@example.com | 90000000 | 216 | 1.00 | normal | **Baseline control** — should match cleanly |
| 01 | Noah Brown | noah.brown@example.com | 90000001 | 207 | 0.37 | normal | |
| 02 | Emma Young | emma.young@example.com | 90000002 | 188 | 0.71 | normal | |
| 03 | Liam Smith | liam.smith@example.com | 90000003 | 181 | 0.38 | normal | |
| 04 | Ava Wilson | ava.wilson@example.com | 90000004 | 191 | 0.76 | normal | |
| 05 | William King | william.king@example.com | 90000005 | 317 | 0.85 | normal | |
| 06 | Sophia Kim | sophia.kim@example.com | 90000006 | 316 | 0.85 | **swapped** | Exercises automatic page-order correction |
| 07 | James Ahmed | james.ahmed@example.com | 90000007 | 306 | 0.70 | **swapped** | Exercises automatic page-order correction |
| 08 | Isabella Wright | isabella.wright@example.com | 90000008 | 280 | 0.38 | normal | |
| 09 | Benjamin Singh | benjamin.singh@example.com | 90000009 | 237 | 0.79 | normal | |
| 10 | Mia Davis | mia.davis@example.com | 90000010 | 314 | 0.29 | normal | |
| 11 | Lucas Scott | lucas.scott@example.com | 90000011 | 266 | 0.42 | normal | |
| 12 | Charlotte Martin | charlotte.martin@example.com | 90000012 | 314 | 0.40 | **swapped** | Exercises automatic page-order correction |
| 13 | Henry Clark | henry.clark@example.com | 90000013 | 283 | 0.68 | normal | |
| 14 | Amelia Green | amelia.green@example.com | 90000014 | 233 | 0.70 | normal | |
| 15 | Alexander Johnson | alexander.johnson@example.com | 90000015 | 317 | 0.39 | normal | |
| 16 | Harper Lewis | harper.lewis@example.com | 90000016 | 205 | 0.54 | normal | |
| 17 | Michael Baker | michael.baker@example.com | 90000017 | 253 | 0.92 | normal | |
| 18 | Evelyn Lee | evelyn.lee@example.com | 90000018 | 310 | 0.44 | **swapped** | Exercises automatic page-order correction |
| 19 | Ethan Walker | ethan.walker@example.com | 90000019 | 171 | 0.73 | **swapped** | Exercises automatic page-order correction |

The tracked filenames are the authoritative DPI/darkness/page-order index.
The swapped-page fixtures exercise automatic page-order correction; a swapped
pair is not by itself an expected failure. The generator documents calibration
and soft-warning limits. All identities are synthetic seed data.

## Regenerating

```
# inside the backend container, after `make dev-seed`:
python scripts/generate_extended_test_scans.py --output-dir ./data/sample_scans
```

Uses a fixed random seed (`RANDOM_SEED` in the script), so re-running
reproduces the chosen conditions unless the script or `seed.py`'s scale-course
roster/exam definitions change; PDF metadata may still differ.
