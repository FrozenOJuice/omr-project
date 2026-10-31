#!/usr/bin/env bash
set -euo pipefail

canvas_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$canvas_dir/.env"

# Windows' python.org installer registers `python`, not `python3` (unlike
# Linux/Mac, which ship both). Prefer python3 where it exists.
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi

base_url="http://${CANVAS_HOST}/api/v1"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

canvas_get() {
  curl --fail --silent --show-error --header "Authorization: Bearer ${CANVAS_API_TOKEN}" "${base_url}$1"
}

echo "Checking the professor profile..."
canvas_get "/users/self/profile" > "$tmp_dir/profile.json"
$PYTHON - "$tmp_dir/profile.json" "$CANVAS_PROFESSOR_EMAIL" <<'PY'
import json
import sys

profile = json.load(open(sys.argv[1], encoding="utf-8"))
if profile.get("login_id") != sys.argv[2]:
    raise SystemExit(f"Unexpected Canvas user: {profile!r}")
print(f"  authenticated as {profile.get('name')} ({profile.get('login_id')})")
PY

echo "Checking the seeded courses..."
canvas_get "/courses?enrollment_type=teacher&state%5B%5D=available&include%5B%5D=term&per_page=100" > "$tmp_dir/courses.json"
$PYTHON - "$tmp_dir/courses.json" <<'PY'
import json
import sys

courses = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {
    "Introduction to Programming",
    "Data Structures",
    "Database Systems",
    "Capstone Project",
}
missing = expected - {course.get("name") for course in courses}
if missing:
    raise SystemExit(f"Missing seeded courses: {sorted(missing)!r}")
wrong_terms = [
    course
    for course in courses
    if course.get("name") in expected
    and course.get("term", {}).get("name") != "Summer Session 2"
]
if wrong_terms:
    raise SystemExit(f"Seeded courses use the wrong term: {wrong_terms!r}")
PY

course_check_index=0
check_course() {
  local course_name="$1"
  local expected_assignments="$2"
  local expected_students="$3"
  local expected_student_count="${4:-}"
  local course_id
  local assignments_file
  local students_file

  course_check_index=$((course_check_index + 1))
  assignments_file="$tmp_dir/assignments-${course_check_index}.json"
  students_file="$tmp_dir/students-${course_check_index}.json"
  course_id="$($PYTHON - "$tmp_dir/courses.json" "$course_name" <<'PY'
import json
import sys

courses = json.load(open(sys.argv[1], encoding="utf-8"))
course = next((item for item in courses if item.get("name") == sys.argv[2]), None)
if course is None:
    raise SystemExit(f"Seeded course {sys.argv[2]!r} was not found")
print(course["id"])
PY
)"

  canvas_get "/courses/${course_id}/assignments?per_page=100" > "$assignments_file"
  canvas_get "/courses/${course_id}/users?enrollment_type%5B%5D=student&enrollment_state%5B%5D=active&per_page=100" > "$students_file"
  $PYTHON - "$assignments_file" "$students_file" "$course_name" "$expected_assignments" "$expected_students" "$expected_student_count" <<'PY'
import json
import re
import sys
from collections import Counter

assignments = json.load(open(sys.argv[1], encoding="utf-8"))
students = json.load(open(sys.argv[2], encoding="utf-8"))
course_name = sys.argv[3]
expected_assignments = set(sys.argv[4].split("|"))
expected_students = set(sys.argv[5].split("|"))
expected_student_count = int(sys.argv[6]) if sys.argv[6] else None

def slug(value):
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")

assignment_names = {item.get("name") for item in assignments}
missing_assignments = expected_assignments - assignment_names
if missing_assignments:
    raise SystemExit(
        f"{course_name} is missing assignments: {sorted(missing_assignments)!r}"
    )

students_by_email = {
    student.get("email") or student.get("login_id"): student
    for student in students
}
if expected_student_count is not None and len(students_by_email) != expected_student_count:
    raise SystemExit(
        f"{course_name} has {len(students_by_email)} students; "
        f"expected {expected_student_count}"
    )
if expected_student_count == 100:
    names = [student.get("name", "").strip() for student in students]
    if any(len(name.split()) < 2 for name in names):
        raise SystemExit(f"{course_name} contains an incomplete student name")
    first_names = [" ".join(name.split()[:-1]) for name in names]
    last_names = [name.split()[-1] for name in names]
    distribution = Counter(Counter(first_names).values())
    expected_distribution = Counter({1: 85, 2: 3, 3: 3})
    if distribution != expected_distribution:
        raise SystemExit(
            f"{course_name} has unexpected first-name duplicates: "
            f"{dict(distribution)}"
        )
    if len(set(last_names)) != 100:
        raise SystemExit(f"{course_name} must contain 100 unique last names")
    for student, first_name, last_name in zip(
        students, first_names, last_names, strict=True
    ):
        email = student.get("email") or student.get("login_id") or ""
        if not email.endswith("@example.com"):
            continue
        expected_email = f"{slug(first_name)}.{slug(last_name)}@example.com"
        if email != expected_email:
            raise SystemExit(
                f"{course_name} contains a non-name-based email: {email!r}"
            )
missing_students = expected_students - set(students_by_email)
if missing_students:
    raise SystemExit(
        f"{course_name} is missing students: {sorted(missing_students)!r}"
    )
invalid_students = [
    students_by_email[email]
    for email in expected_students
    if not str(students_by_email[email].get("sis_user_id", "")).isdigit()
    or len(str(students_by_email[email].get("sis_user_id", ""))) != 8
]
if invalid_students:
    raise SystemExit(
        f"{course_name} students are missing OMR identities: {invalid_students!r}"
    )

print(
    f"  {course_name}: {len(expected_assignments)} assignments, "
    f"{len(students_by_email)} importable students"
)
PY
}

echo "Checking seeded assignments and rosters..."
check_course \
  "Introduction to Programming" \
  "Quiz 1|Midterm Exam|Final Exam" \
  "maya.chen@example.com|liam.wilson@example.com|ava.patel@example.com|noah.kim@example.com|sofia.martinez@example.com|ethan.nguyen@example.com|olivia.brown@example.com|lucas.anderson@example.com|emma.thompson@example.com|jackson.lee@example.com|invitation.student@example.com" \
  "100"
check_course \
  "Data Structures" \
  "Trees and Graphs Quiz|Midterm Exam|Final Exam" \
  "liam.wilson@example.com|ava.patel@example.com|noah.kim@example.com|sofia.martinez@example.com|ethan.nguyen@example.com|olivia.brown@example.com|lucas.anderson@example.com|emma.thompson@example.com|jordan.foster@example.com|chloe.sullivan@example.com"
check_course \
  "Database Systems" \
  "SQL Quiz|Database Design Midterm|Final Exam" \
  "sofia.martinez@example.com|ethan.nguyen@example.com|olivia.brown@example.com|lucas.anderson@example.com|emma.thompson@example.com|jackson.lee@example.com|chloe.sullivan@example.com|marcus.reed@example.com"
check_course \
  "Capstone Project" \
  "Project Check-in|Final Presentation" \
  "maya.chen@example.com|noah.kim@example.com|olivia.brown@example.com|lucas.anderson@example.com|jackson.lee@example.com|marcus.reed@example.com"

echo "Canvas API smoke test passed."
