# OMR System: from scanned exams to reviewed results

**Role:** Full-stack contributor, six-person COSC 499 capstone team  
**Institution:** University of British Columbia Okanagan  
**Project:** Team 15, 2026  
**Technologies:** Angular, TypeScript, FastAPI, Python, Go, OpenCV, PostgreSQL,
Garage, Docker Compose, and Canvas REST API

## Problem

Paper multiple-choice exams are convenient for students, but instructors need a
reliable way to turn scanned answer sheets into grades. Recognition is only part
of the task: uncertain marks need review, corrections need a history, students
need controlled access to released results, and grades need to reach the LMS.

## What the team built

OMR System brings exam setup, custom bubble-sheet templates, scanned PDF upload,
automatic recognition, grading, human review, analytics, student review requests,
and Canvas grade release into one browser application. A separate Go/OpenCV
service handles recognition while FastAPI coordinates the exam workflow.

[Explore the screenshots](screenshots/README.md) and
[architecture](architecture.md).

## My role

My work focused on authentication and account management, Canvas integration,
and exam/template workflows. This included password recovery and administrator
account management; Canvas course imports, roster syncing, grade release and
student result links; and contributions to exam templates, scanned answer-key
uploads, academic terms, and branding.

The project was collaborative. The [contribution summary](contributions.md)
distinguishes these areas from the team's overall accomplishments and identifies
the final-report evidence behind the summary.

## Engineering decisions

### Separate recognition from exam management

The Go/OpenCV service owns PDF preprocessing and mark detection. FastAPI owns
grades, permissions, review states, and release. This boundary lets the web
application work with recognition results without embedding native image-processing
logic in the API or frontend. It also gives the grader an independently testable
HTTP interface.

### Keep ambiguous cases visible

Automatic detection can encounter blank or multiple marks, mismatched versions,
and uncertain identities. The application exposes the scanned sheet alongside
detected responses and grading controls. Human review is part of the workflow,
with corrections and release history recorded rather than hidden behind a final
score.

### Connect the workflow to Canvas

The Canvas integration connects external course, roster, assignment, and grade
data to the application's own records. Stored personal access tokens are
encrypted. Grade-release results distinguish successes, skipped records, and
failures, while time-limited student links provide a route back to marked results.
These workflows required coordination across API contracts, account identity,
database relationships, and frontend states.

## Validation and outcome

The team delivered a working capstone covering the exam lifecycle, accompanied
by automated tests and two rounds of usability testing. The final report records
changes made after feedback, including clearer answer-key navigation and a
confirmation before releasing results. See [testing evidence](testing.md) for
the distinction between recorded submission results and current checks.

The OMR service report includes component benchmarks with hardware and workload
details. Those measurements are team results, not a benchmark of the complete web
workflow. The planned 10,000-student capacity was not independently demonstrated
in the retained evidence.

## Reflection

The project strengthened my ability to deliver features across a frontend, API,
database, and external integration. I learned to split integration work into
smaller changes and to treat failure and review states as part of the user flow.
Earlier interface contracts and more end-to-end validation would improve the
same development process in a future project.

## Credit and availability

Built by Kaden Harris, Joel deHoog, Nathan Worth, Chad Glazier, Graeme Brown, and
Tyson Livadney. See [contributors and upstream provenance](../../CONTRIBUTORS.md).
The original reports are preserved; this portfolio copy retains the AGPL-3.0
license. Public repository release awaits confirmation of university/team
publication terms and outstanding asset permissions. A hosted public demo is not
part of this portfolio preparation.
