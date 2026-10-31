# Joel deHoog's contributions

I worked across Angular, FastAPI, PostgreSQL, and Canvas integration as part of
Team 15's six-person capstone project. My initial role was frontend development;
the team later organized work around complete features spanning the stack.

My contribution areas, as recorded in my final-report reflection, were:

| Area | Work | Representative implementation |
| --- | --- | --- |
| Authentication and accounts | Authentication, password recovery, and administrator account management | [`auth_credentials.py`](../../app/backend/services/auth_credentials.py), [`auth_passwords.py`](../../app/backend/services/auth_passwords.py), [`admin_users.py`](../../app/backend/services/admin_users.py), account/admin Angular components |
| Canvas LMS integration | Course import, roster synchronization, grade release, and secure student result links | [`canvas_courses.py`](../../app/backend/services/canvas_courses.py), [`canvas_roster.py`](../../app/backend/services/canvas_roster.py), [`canvas_grades.py`](../../app/backend/services/canvas_grades.py), [`canvas_student_access.py`](../../app/backend/services/canvas_student_access.py) |
| Exams and configuration | Exam templates and sections, scanned answer-key uploads, academic terms, and some branding work | [`answer_key_scan_extraction.py`](../../app/backend/services/answer_key_scan_extraction.py), [`academic_terms.py`](../../app/backend/services/academic_terms.py), template and answer-key Angular components |

These are areas I contributed to, not claims that I solely authored every linked
file. Other team members contributed across the same features. The OMR engine,
statistics, review interfaces, storage, and surrounding workflows are team work;
the complete application should always be credited to all six contributors.

## Evidence and limits

The sources are the final report's [feature matrix](../final/OMR%20System%20Final%20Project%20Report.md#31-complete-feature-list)
and [personal reflections](../final/OMR%20System%20Final%20Project%20Report.md#73-personal-and-team-growth).
The representative files show where the implementation lives; they do not prove
line-by-line authorship. Original PR or issue links can be added when verified.
This imported repository does not support contribution percentages or commit-count
comparisons between team members.

## What I learned

Building complete workflows increased my confidence across the stack. The Canvas
integration reinforced the value of dividing complex work into smaller, testable
changes. In a future project I would define integration contracts earlier and
plan more end-to-end validation before connecting the individual components.
