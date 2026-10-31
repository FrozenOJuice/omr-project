# OMR handler fixtures

Identity-page PNGs and their copies in the batch PDFs use **Alex Example** and
the synthetic ID `90009999`. The expected marking JSON uses the same identity.
No contributor's student number is intended to appear in these public-copy
fixtures. Identity fields were regenerated for portfolio privacy; original answer
mark patterns, anchors, page orders, and upside-down test scenarios are retained.

Identity pages use PNG to keep the original grayscale decoder's anchor pixels
lossless. Recompressing the scans to JPEG can change confidence enough to break
the existing preprocessing tests. Do not lower recognition thresholds to hide a
fixture regression.

The tests exercise recognition, not real student grades. See
[`tools/portfolio/prepare_assets.py`](../../../../../../tools/portfolio/prepare_assets.py)
for deterministic identity-field regeneration and the portfolio publication page
for remaining permissions/history considerations.
