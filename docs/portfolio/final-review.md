# Final security review

Reviewed **31 October 2026** for `FrozenOJuice/omr-project`, commit
`22be7a91a8c247fd9310351288a25a89d32a791f` ("Import cleaned OMR System copy").
The repository was private and had one reachable commit with a clean working tree
when the review began. This report and accompanying documentation edits are a
subsequent local change; they have not been committed or pushed by the reviewer.

## Assessment

The earlier student numbers and personal invitation address were not found by
the targeted checks of this cleaned import. The older unsafe import is absent
from this repository's reachable history. Both configured CI jobs passed for the
reviewed commit. Another history reset is not required to remove those old values
based on the evidence checked here.

This is **not a complete security certification**. Current dependency versions
match published advisories, and known application access-control issues remain.
A source-code portfolio and a publicly reachable application require different
risk decisions. No feature, dependency, license, asset, deployment, history, or
visibility changes were made during this final review.

## Evidence and boundaries

- Reviewed 811 tracked files, including 711 UTF-8 text files. Searched for the
  original six charter IDs and invitation address without printing their values;
  no targeted matches were found in tracked raw contents.
- The asset verifier confirmed six gallery screenshots match the report's pixels,
  five identity-page PNGs use the synthetic identity, and eleven embedded PDF
  identity images and the expected-results JSON agree with it.
- Parsed 51 PDFs (259 pages), checked extracted text for personal-provider emails,
  and checked for attachments and active JavaScript/launch/form actions. No such
  emails, embedded attachments, or active action types were found. The OMR service
  report's opening action resolves to a page-view destination, a harmless finding.
- Checked 48 tracked raster images for GPS/serial-number EXIF fields and obvious
  personal-email/workstation-path text metadata; no targeted findings. This is
  not exhaustive image OCR or forensic metadata analysis.
- Pattern checks found no common provider-token or private-key blocks in scanned
  tracked text. Long hexadecimal credential assignments were limited to the
  documented disposable Garage configuration files. No production credential
  exposure was established. This does not exclude every secret format.
- No tracked database dumps, runtime database files, logs, dependency directories,
  or completed private environment files were identified. Tracked environment
  examples and the documented Garage test environment are intentional. No tracked
  file matched the current ignore rules.
- `git rev-list --all --count` returned one; Git's integrity check reported no
  unreachable objects. Author and committer emails use GitHub noreply addresses.
  The root AGPL license matches the original byte-for-byte.
- [CI run 41242912328](https://github.com/FrozenOJuice/omr-project/actions/runs/41242912328)
  completed successfully on 31 October 2026 for the reviewed SHA. Both
  `repository` and `frontend` jobs and their source/portability/install/test steps
  succeeded. This run does not include a dependency security audit.

No databases, mail delivery, live Canvas operations, production services, or
application endpoints were exercised. No penetration testing was performed.

## Security findings

| Finding | Evidence | Consequence / next action |
| --- | --- | --- |
| High: dependency advisory matches, including upstream critical ratings | `app/backend/requirements.txt`, `app/frontend/package-lock.json`, and [dependency-review.json](dependency-review.json) | Triage affected functionality and plan compatible upgrades with regression testing before deployment or processing untrusted input. A passing functional CI run does not establish dependency safety. |
| High: scan authorization checks role without course ownership | `app/backend/routers/scan_router.py:18`, `:46`, `:72`; `services/scans.py:24`, `:59`; `dependencies/auth_dep.py:31` | Staff can reach scan lookup/deletion paths without course-specific checks in the reviewed call chain. Public professor registration makes role alone insufficient. Review before hosting with untrusted users or real records. |
| High: registration claims roster identities without proving email ownership | `app/backend/services/auth_credentials.py:18`, `services/course.py:581` | Knowing a matching email/student number may allow claiming an unlinked roster identity. Add verified claiming before handling real student data. No exploit attempt was made. |
| Medium: development defaults and network exposure | `app/garage.toml`, `app/omr/scripts/config/garage.env`, `app/omr/internal/httpserver/start.go:32`, `app/docker-compose.dev.yml:44` | Garage defaults are confirmed disposable; OMR has a fallback admin key and development ports bind through Docker. Keep demonstration services isolated and configure private credentials/network controls for a shared deployment. |
| Medium: unversioned external script/style resources | `app/omr/pages/index.html:24` loads Stoplight Elements from unversioned unpkg URLs | Source lockfiles do not pin what a visitor's browser receives. Review version pinning, trust, and delivery before deployment. |
| High operational risk if tests target the wrong data | `app/backend/tests/conftest.py:238` and `:292`; `tests/test_storage.py:92` | Backend tests migrate/downgrade their selected database; storage tests write/delete objects. Use disposable targets. This behavior is documented and was not changed. |

These deployment risks do not establish that publishing source exposes a running
server or that any system has been compromised. They do prevent an unqualified
claim that the capstone is production-secure.

## Dependency review

Read-only npm audits ran against temporary copies of the frontend manifests;
no packages were installed and no package scripts were executed:

| Scope | Reported result |
| --- | --- |
| Frontend, all dependencies | 49 flagged package entries: 3 critical, 21 high, 23 moderate, 2 low |
| Frontend, production dependencies only | 6 flagged entries: 4 high, 2 moderate, no critical |
| Backend explicit pins | 33 package/version pins queried against GitHub's reviewed public advisory API; 53 advisory records returned: 5 critical, 28 high, 20 medium |

These totals count different things: npm package entries can inherit the same
underlying issue, while Python totals count advisory records. They must not be
added together or described as proven independent application vulnerabilities.
The critical npm entries (`piscina`, `proxy-addr`, and `tar`) are development-only
in the reviewed lockfile. The production-only entries are Angular packages.

Examples requiring triage:

- Pinned Starlette `0.38.6` falls in the affected range of
  [GHSA-f96h-pmfr-66vw](https://github.com/advisories/GHSA-f96h-pmfr-66vw), concerning
  multipart form resource exhaustion. The application has form upload routes.
- Pinned Pillow `11.2.1` falls in the affected range of
  [GHSA-v9pv-5gc8-w2m6](https://github.com/advisories/GHSA-v9pv-5gc8-w2m6), concerning
  multi-frame image memory corruption. The specific affected decoder path was
  not established as reachable in this application.
- Angular `21.2.16` packages match published advisories, including
  [GHSA-jj27-h5hq-8x99](https://github.com/advisories/GHSA-jj27-h5hq-8x99).
  Several Angular results concern optional hydration/transfer-cache/i18n paths;
  package presence alone does not prove those paths are used.

[Machine-readable evidence](dependency-review.json) records versions, advisory
links, and scopes. It is a dated snapshot. Go modules, container/native libraries,
transitive Python resolution, and externally fetched assets were not exhaustively
scanned. No automatic audit fix, dependency upgrade, or exploit test was run.

## Next decisions

1. Keep the cleaned history; no further reset is indicated by the targeted checks.
2. Retain the CI run as evidence for the exact reviewed commit; let the next
   documentation commit receive its own CI result after the user pushes it.
3. Treat dependency remediation and application authorization changes as separate
   implementation tasks. They were not included in this documentation-only review.

The review supports accurate presentation of the capstone's current state. It
makes no guarantee that all sensitive data or vulnerabilities have been found.
