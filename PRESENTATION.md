# Presentation Quick Reference

Run commands from the repository root.

## Start and reset

```bash
make presentation-up      # start, seed, generate uploads, and check both apps
make presentation-data    # rebuild only the ignored upload files
make presentation-check   # verify the OMR and Canvas stacks
make presentation-status  # show both stacks
make presentation-down    # stop both stacks without deleting data
```

`make presentation-up` is idempotent and preserves work created during a
rehearsal. Use a full reset when the empty accounts or student requests must
return to their original state:

```bash
make dev-db-clear
make canvas-reset
make canvas-setup
make presentation-up
```

The reset is destructive. Do it before presentation day, not as a last-minute
recovery step.

Generated upload files live under
`app/backend/data/presentation_flows/` and are Git-ignored.

## Links

| Application | URL |
| --- | --- |
| OMR System | <http://localhost:4200> |
| Canvas | <http://localhost:6700> |
| Backend API documentation | <http://localhost:8000> |

Every seeded OMR and Canvas account uses `Password123!`.

The invitation student's published address is synthetic. Keep
`EMAIL_CONSOLE_MODE=true` and use `make logs-email-dev` to inspect the invitation
link without sending mail. No real mailbox is required for the portfolio demo.

## Presentation entry points

| Flow | Login | Starting state |
| --- | --- | --- |
| Empty professor / Canvas | `empty.prof@example.com` | Starts empty and represents the same professor in both systems |
| Seeded professor | `test.prof@example.com` | Complete courses, exams, scans, analytics, and review states |
| Student results — video | `james.ahmed@example.com` | Included in the manual roster and student-scan batch |
| Student results — live | `jordan.lee@example.com` | Separate released result with no existing review request |
| Canvas invitation | `invitation.student@example.com` | Canvas-only student, pending after COSC 111 import |
| Administrator | `admin@example.com` | Site-wide administration |
| Canvas professor | `empty.prof@example.com` | Owns the local Canvas demonstration courses |

The separate empty-professor, video-student, and live-student accounts keep the
main demonstration paths isolated while the professor identity remains
consistent between OMR and Canvas.

## Flow data

### 1. Empty professor

Use `01-empty-professor/` when demonstrating the full manual workflow. It
contains:

- `roster-100.csv`: 20 existing OMR accounts and 80 pending students. Three
  first names occur twice, three occur three times, the remaining 85 occur
  once, and all 100 last names are unique. Emails use the visible student's
  name in `first.last@example.com` form.
- `default-10-a-e/`: a standard 10-question A–E template with answer keys and
  one nine-sheet student batch.
- `mixed-15-a-k/`: the sectioned 15-question A–K/T–F template, marked and
  unmarked answer-key options, and one nine-sheet student batch.

Each normal student batch contains eight clean version A/B sheets plus a ninth
Version A sheet with a double-bubbled answer. One upload therefore
demonstrates both automatic processing and the review-required path.

The default option is:

- Name: `Default Exam (10 Questions A-E)`
- Versions: 2
- One `Multiple Choice` section, questions 1–10, options A–E

The mixed option is:

- Name: `Mixed-Format Exam (15 Questions A-K)`
- Versions: 2
- Section 1: `Multiple Choice`, questions 1–10, options A–K
- Section 2: `True or False`, questions 11–15, options T/F

### 2. Seeded professor

The seeded professor can start at any checkpoint:

- **COSC 221 — Quiz 1:** registered template, answer key not defined.
- **COSC 221 — Midterm Exam:** completed, review-required, and failed scans;
  intentionally unreleased.
- **COSC 221 — Final Exam:** released grades and mixed regrade-request states.
- **COSC 304 — Database Systems Final Exam:** 24 questions, three versions,
  and analytics scenarios for difficulty, discrimination, and distractors.
- **COSC 499 — Default 10-Question Upload Exam:** A–E template, both answer
  keys, 200 enrolled students, and no scans.
- **COSC 499 — Mixed 15-Question Upload Exam:** A–K/T–F template, both answer
  keys, 200 enrolled students, and no scans.
- Archived offerings and a 100-question UBC blueprint remain available for
  comparison, archive, and large-template demonstrations.

Use the matching `02-seeded-professor/default-10-a-e/` or
`02-seeded-professor/mixed-15-a-k/` files on those exams. Each option includes
answer keys and a single clean-plus-review student batch.

### 3. Canvas from scratch

The local Canvas **COSC 111 — Introduction to Programming** course has 100
students. Importing it links ten existing OMR users and leaves 90 pending.
The OMR course itself is not pre-imported. It uses the same restrained
first-name distribution as the CSV roster, with 100 unique last names and
name-based email addresses.

Use `03-canvas-from-scratch/` after connecting `empty.prof@example.com` to
Canvas. Both template folders contain answer keys and a six-sheet batch with
five clean, uniquely linked students and Ethan Nguyen's review-required sheet.
Four additional linked students remain available as backups.

### 4. Student results and regrade

Taylor and Jordan are enrolled in **COSC 221 — Data Structures** and each has
a released **Final Exam** result without a seeded regrade request. These are
backup student flows and need no upload file.

### 5. Canvas invitation and claiming

After importing COSC 111, Graeme (`33333333`) remains a pending roster entry.
Invite Graeme individually so the other pending test addresses are not
emailed. Each template folder under `05-canvas-invitation/` contains
`invitation-student-scan.pdf` for use after the account is claimed.

## Other seeded accounts

- `test.coprof@example.com`: promoted co-professor permissions.
- `joe.blow@example.com`, `joe.mama@example.com`, and
  `joe.shmoe@example.com`: existing student and scan-review scenarios.
- `admin@canvas.test`: local Canvas administrator.
