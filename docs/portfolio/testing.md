# Testing evidence and prerequisites

## Portfolio validation: 31 October 2026

| Check | Result | Scope |
| --- | --- | --- |
| Frontend | **53 files / 936 tests passed** | Current source copied into an isolated container using the cached frontend test image; `npm test -- --watch=false` |
| OMR fixture-dependent packages | **Handler, scanner, and PDF tests passed** | Updated synthetic identities and replacement PDFs exercised with the cached project OpenCV image |
| OMR remaining suite | **Passed with two explicit exclusions** | `go test ./... -count=1 -skip='^(TestCurrentCpuInfo\|TestCpuHistory)$'`; all packages checked, except those two VM-dependent test functions |
| Canvas shell portability | **Passed** | Existing test script uses fake commands and temporary files; no Canvas service contacted |
| Offline repository checks | Python/shell/JSON syntax and new portfolio local links checked | `python tools/portfolio/check_repository.py`; imports no application modules and opens no service connections |
| Asset and privacy checks | **Passed** | Six screenshots match report pixels; five PNG and eleven PDF identity images use synthetic data; former charter IDs absent from checked current text/PDF/identity fields |
| Backend suite | **Not rerun during this preparation** | Submission-era results remain in the original report; no fresh backend pass is claimed |
| Fresh installation, production deployment, live Canvas, and email | **Not exercised** | No application data or running database was reset |

OMR validation used temporary container storage, networking disabled, and a
read-only source mount. The initial privacy edit exposed an anchor sensitivity;
the final identity images preserve the original decoder's grayscale anchor pixels
losslessly. No recognition thresholds, grading rules, or application code were
changed to make tests pass.

The full OMR command encounters two CPU-metadata tests in `internal/sys` on this
Docker Desktop VM: `TestCurrentCpuInfo` and `TestCpuHistory` expect a CPU description
and clock frequency that the VM does not provide. Record those failures explicitly;
do not equate a selected-package pass with an unqualified full-suite pass.
The same two failures were reproduced against the untouched import in the same
container environment. No tests or assertions were removed from the source.

## CI scope

The former pytest workflow was entirely commented out. The replacement
[`Repository checks`](../../.github/workflows/ci.yml) workflow runs offline source
checks, Canvas shell portability checks, and the frontend suite on pushes/PRs.
It requires no project secrets or live Canvas/Resend credentials.

Backend and OMR are not claimed as CI jobs. Backend CI needs a correctly
provisioned disposable PostgreSQL/Garage environment; OMR needs the native-library
image and an appropriate hardware-metadata environment. No GitHub Actions run
has been triggered by this local preparation.

## Backend test isolation

The normal backend command is `make test-backend`; targeted commands are listed
in the root README. Before running any backend tests:

1. Use a disposable test database only. Keep `TEST_DATABASE_URL` pointed at the
   Compose `db_test` service and `capstone_test` database, with credentials matching
   `.env.dev`. Never point it at development or production records.
2. Be aware that the autouse session fixture applies migrations and runs
   `alembic downgrade base` during teardown. There is no automatic guard rejecting
   an inappropriate target. A missing URL can skip tests rather than validate them.
3. The real storage integration test uploads, downloads, and deletes objects.
   Configure a disposable Garage bucket with the necessary permissions; do not
   supply production storage credentials. `make test-storage` now references the
   existing storage module only.
4. Ensure `.env.dev` supplies all settings required when modules are imported.
   The backend uses ASGI request tests and many mocked integrations; the suite
   still needs its configured services. Email tests clear the real delivery key.

The safeguards above document the existing suite's behavior. Test fixtures and
application authentication/authorization behavior were not redesigned for this
portfolio preparation.

## Historical evidence

- The original final report PDF embeds backend passing-test output and a frontend
  result showing 936 passing tests across 53 files. These are submission-era
  results and should not be presented as a new run of every service.
- [`app/omr/coverage.txt`](../../app/omr/coverage.txt) records **81.2% statement
  coverage for selected OMR packages**. Middleware is 51.0%. The coverage script
  explicitly selects packages, so the total is not application-wide coverage.
- The report documents two usability-testing rounds and subsequent changes.
  Some fixes were checked only by the team, not a third external testing round.
- Component performance numbers in the OMR service report include hardware and
  workload details. No retained final benchmark demonstrates 10,000-student
  end-to-end capacity.

See [original reports](../TOC.md) for this evidence. Coverage generation commands
remain in the root README; rebuilding the relevant images is necessary if the
dependency environment changes.

Asset preparation is separate from the application runtime. Its optional tooling
dependencies are pinned in [`tools/portfolio/requirements.txt`](../../tools/portfolio/requirements.txt).
After installing them into a tooling environment, run
`python tools/portfolio/verify_assets.py`. In the original private repository,
`--legacy-ref 83ab149` additionally checks the former charter IDs without printing
their values. That private historical ref is intentionally absent from an export.
