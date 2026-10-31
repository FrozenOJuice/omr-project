# PDF rendering fixtures

`sample.pdf` is an original five-page synthetic document; `sample_large.pdf` is
an original 88-page synthetic document. Their page counts are deliberate inputs
to the existing page partitioning/range tests. The geometric `sample_image.png`
and malformed `not_a_pdf.jpg` image are original synthetic content. The malformed
text file is original plain text.

The small scanned documents in `samples/` retain the original page-count and
scan-order scenarios, with real contributor identification replaced by a
synthetic identity wherever present. The handler fixture README describes it.

Generate the synthetic documents and identity fields with
`python tools/portfolio/prepare_assets.py fixtures` from the repository root
(Pillow, pypdf, and reportlab are tooling dependencies). This does not run the
application, query a database, or change a recognition algorithm.
