# OMR System

An Optical Mark Recognition and Exam Management System built by a six-person
University of British Columbia Okanagan capstone team for COSC 499 in 2026.
Instructors can create bubble-sheet exams, upload scanned PDFs, review ambiguous
marks, analyze results, and release grades through Canvas LMS. Students can view
released results and request a review.

**Stack:** Angular / TypeScript · Python / FastAPI · Go / OpenCV · PostgreSQL ·
Garage S3-compatible storage · Docker Compose · Canvas REST API.

**Joel deHoog's work** focused on authentication and account management, Canvas
integration, and exam/template workflows. Features were developed collaboratively;
see [individual contributions](docs/portfolio/contributions.md) and
[all six contributors](CONTRIBUTORS.md).

[Case study](docs/portfolio/case-study.md) ·
[Screenshot gallery](docs/portfolio/screenshots/README.md) ·
[Architecture](docs/portfolio/architecture.md) ·
[Testing evidence](docs/portfolio/testing.md) ·
[Publication review](docs/portfolio/publication.md) ·
[Final security and asset review](docs/portfolio/final-review.md)

![Exam review with the scanned sheet, detected answers, and grade controls](docs/portfolio/screenshots/exam-review.png)

## Engineering highlights

- A separate Go/OpenCV service preprocesses batch PDFs and detects marks; FastAPI
  applies grading rules and manages review, audit history, and grade release.
- Multipart uploads send chunks directly to object storage through presigned URLs.
- Canvas integration connects course/roster import, assignment linking, grade
  release, and time-limited student result links.
- Reusable templates, multiple exam versions, partial credit, and human review
  handle cases that cannot be resolved reliably by automatic detection alone.
- Automated frontend, backend, and OMR tests accompany the implementation. See
  the testing page for current validation and historical coverage evidence.

This is a portfolio presentation of an existing team project. The original
[final reports](docs/TOC.md) are retained as capstone evidence. University/team
publication permissions are still being confirmed; the existing
[AGPL-3.0 license](LICENSE) is unchanged. This repository starts with a cleaned source import of the team project; the
original private import history is excluded. The team's complete development
history remains in the original project repository.

## Running locally

Run commands from the repository root.

Before starting, create `app/.env.dev` or `app/.env.prod` from the corresponding `.example` file and fill in the required values.
For a fresh development installation, follow the [local setup notes](docs/portfolio/local-setup.md),
including Garage provisioning. The retained production configuration needs additional
deployment work; a public server is not required for the portfolio.

For the combined OMR and Canvas demonstration workflow, see
[`PRESENTATION.md`](PRESENTATION.md).

## Development

```bash
make dev             # start
make dev-down        # stop
make dev-logs        # logs
make logs-email-dev  # live email activity (recipient, subject, link)
make check-dev       # status and health
make dev-seed        # migrate and seed the development database
make dev-archive     # process archive retention deadlines currently due
make dev-db-clear    # wipe dev db data without restarting containers
```

`make dev-archive` runs one retention-processing pass against the development database. It asks for confirmation because due scanned images and student-linked exam records are permanently removed.

`make logs-email-dev` streams email activity. In development (`EMAIL_CONSOLE_MODE=true`) emails are logged with their links instead of being sent, so you can copy a link (e.g. a set-password or course-join link) and test the flow without a real email service. Set `EMAIL_CONSOLE_MODE=false` with a real `RESEND_API_KEY` to send for real.

Frontend: `http://localhost:4200`

Backend docs: `http://localhost:8000/docs`

## Bootstrap Admin

```bash
make create-admin EMAIL=admin@example.com FIRST_NAME="Admin" LAST_NAME="Dude"
```

## Seeding Test Data

Populate the complete development dataset with sample users, professional-looking
courses, exams, answer keys, realistic scans, statistics, and historical data:

```bash
make dev-seed
```

The seed is idempotent. It starts PostgreSQL, Garage, and the OMR service, renders a
small set of filled bubble-sheet PDFs through the real pipeline, and fabricates the
larger analytics datasets directly for speed. Manual-upload fixtures remain available
under `app/backend/data/sample_scans/`.

Ten students match the local Canvas COSC 111 roster, so importing that course
demonstrates automatic account linking. A separate synthetic Canvas-only student
demonstrates the invitation flow. Published fixtures use reserved example addresses;
console email mode lets you inspect links without sending mail.
Archived 2023 and 2024 COSC 221 offerings include graded exams for demonstrating the
course-comparison timeline against the current offering.

## Testing

Read [test prerequisites and evidence](docs/portfolio/testing.md) first. Backend
tests migrate and then downgrade the configured test database, and storage
integration tests write and delete objects. Use isolated disposable services.

```bash
make test-frontend  # all frontend tests
make test-backend   # all backend tests
make test-omr       # all OMR tests
make test-admin     # admin tests
make test-auth      # auth tests
make test-courses   # course tests
make test-database  # database tests
make test-storage   # garage/storage tests
```

## Test Coverage

Run coverage commands from the `app/` directory after the development images have already been built. Generated coverage reports are ignored by git.

Backend coverage:

```powershell
cd app
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm backend pytest tests --cov=. --cov-report=term-missing --cov-report=html
```

The backend HTML report is written to `app/backend/htmlcov/index.html`.

OMR coverage:

```powershell
cd app
New-Item -ItemType Directory -Force omr/coverage
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --entrypoint sh -v "${PWD}/omr/coverage:/coverage" omr_service -c "go test ./... -coverprofile=/coverage/coverage.out && go tool cover -func=/coverage/coverage.out && go tool cover -html=/coverage/coverage.out -o /coverage/coverage.html"
```

The OMR HTML report is written to `app/omr/coverage/coverage.html`.

Frontend coverage:

```powershell
cd app/frontend
npm test -- --watch=false --coverage --coverage-reporters=text --coverage-reporters=html
```

The frontend HTML report is written to `app/frontend/coverage/frontend/index.html`.

If coverage dependencies or Docker images change, rebuild the affected service before running coverage.

## Production

```bash
make prod              # build and start
make prod-down         # stop
make prod-logs         # logs
make check-prod        # status and health
make logs-migrate-prod # failed migration logs
```

Production exposes the frontend on `APP_PORT` from `app/.env.prod`.
