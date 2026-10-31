# Local Canvas LMS

Local Canvas test environment for API development. It runs Canvas, PostgreSQL,
Redis, and a background worker in Docker. It is not intended for production.

## Setup

Requires Docker Desktop and Git. The first build is large and can take a while.

```sh
make canvas-setup
```

When setup finishes, open <http://localhost:6700>.

To test the project integration, also run `make dev-up`, sign in to the
project as a professor, and connect the local Canvas account with an access
token:

1. Sign in to Canvas as `empty.prof@example.com`.
2. Open **Account > Settings**.
3. Under **Approved Integrations**, choose **+ New Access Token**.
4. Give the token a purpose such as `Local OMR`, generate it, and copy it.
5. In OMR, open **Account**, choose **Connect Canvas**, and paste the token.

Canvas only shows a newly generated token once. Treat it like a password and
revoke it from Canvas Settings when it is no longer needed. OMR encrypts its
stored copy and never displays it again.

The current integration is instructor-facing: professors and administrators
can import courses and rosters, link assignments, and send grades. Student-side
Canvas account linking is outside this phase. OMR remains fully usable without
Canvas configured or connected.

Each imported OMR course belongs to the account that imported it. Another
instructor can import the same Canvas course into their own OMR course.

For later use:

```sh
make canvas-up
make canvas-down
```

Stopping Canvas preserves its data.

## Seed data

All accounts use the password `Password123!`.

| Role | Login |
| --- | --- |
| Administrator | `admin@canvas.test` |
| Professor | `empty.prof@example.com` |
| Maya Chen | `maya.chen@example.com` |
| Liam Wilson | `liam.wilson@example.com` |
| Ava Patel | `ava.patel@example.com` |
| Noah Kim | `noah.kim@example.com` |
| Sofia Martinez | `sofia.martinez@example.com` |
| Ethan Nguyen | `ethan.nguyen@example.com` |
| Olivia Brown | `olivia.brown@example.com` |
| Lucas Anderson | `lucas.anderson@example.com` |
| Emma Thompson | `emma.thompson@example.com` |
| Jackson Lee | `jackson.lee@example.com` |
| Jordan Foster | `jordan.foster@example.com` |
| Chloe Sullivan | `chloe.sullivan@example.com` |
| Marcus Reed | `marcus.reed@example.com` |
| Graeme B | `invitation.student@example.com` |
| Generated presentation students | Name-based `first.last@example.com` addresses |

The professor is enrolled in four presentation-ready courses under the current
`Summer Session 2` term:

| Course | Students | Assignments |
| --- | ---: | ---: |
| COSC 111 — Introduction to Programming | 100 | 3 |
| COSC 221 — Data Structures | 10 | 3 |
| COSC 304 — Database Systems | 8 | 3 |
| COSC 499 — Capstone Project | 6 | 2 |

COSC 111 is the presentation-scale Canvas import: it contains exactly 100
students. Ten students use the same email and student number as the OMR
development seed, so those accounts link automatically and provide unique
recipients for scan and grade-release demonstrations. The other 90 remain
pending until they register, including Graeme B (`33333333`) for the optional
invitation-email demonstration. Its names are intentionally
realistic but restrained: three first names occur twice, three occur three
times, the other 85 occur once, and every last name is unique. Generated
accounts use name-based email addresses rather than numbered placeholders.

The professor API token used by `make canvas-smoke` and the other local
settings are created automatically. This smoke-test token is separate from the
token you generate in Canvas and paste into OMR. Local secrets live in the
ignored `tools/canvas/.env`.

## Other commands

```sh
make canvas-ps       # show service status
make canvas-logs     # follow logs
make canvas-restart  # restart all services
make canvas-seed     # restore the complete presentation dataset
make canvas-smoke    # test the Canvas API
make canvas-build    # rebuild the Canvas image
make canvas-config   # validate Docker Compose
make canvas-reset    # delete all Canvas containers and data
make test-canvas-scripts  # test the cross-platform command wrappers without Docker
```

When the seed definition and settings are unchanged, `make canvas-seed`
verifies the live presentation data and skips the expensive Rails boot. If
verification fails, it automatically runs the full idempotent seed. Use
`make canvas-seed FORCE=true` to force a complete reconciliation.

After `make canvas-reset`, run `make canvas-setup` again.

The setup uses the pinned Canvas release in `.env.example` and keeps the cloned
Canvas source in the ignored `tools/canvas/canvas-lms/` directory. To change the
port, update both `CANVAS_PORT` and `CANVAS_HOST` in `tools/canvas/.env`.
