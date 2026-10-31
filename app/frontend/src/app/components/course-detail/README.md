# Course detail architecture

`CourseDetail` is the route component for `/courses/:id`. It remains the coordinator for course loading, route/query handling, charts, and the exam, grading, student, review-request, template, and scan workflows.

## Local components

- `sections/course-header` owns the course identity and header actions. It receives the course and management state, then emits navigation, statistics, template, edit, and archive/delete actions. It must not call APIs directly.
- `modals/course-comparison-modal` owns historical-course loading, comparison CRUD, exam mapping overrides, and the historical-average chart. It receives the current course and its already-loaded statistics.
- `course-detail.ts` remains the integration boundary. State shared across multiple workflows should stay here until the entire workflow can be moved behind a small input/output contract.

Keep section and modal folders shallow: add a folder only for a cohesive page region or workflow, not for individual buttons or rows.

## Changes that affect this page

Review these dependencies whenever `CourseDetail` changes:

- `app.routes.ts` defines the `/courses/:id` route.
- `components/courses` redirects legacy notification links and navigates into the page.
- `services/course.service.ts` supplies course, roster, statistics, archive, and comparison APIs.
- `services/exam.service.ts`, `services/exam-template.service.ts`, and `services/review-request.service.ts` supply the exam workflows coordinated by the page.
- `models/course.model.ts`, `models/exam.model.ts`, and `models/exam-template.model.ts` shape the view state. Exam template section fields are consumed by grade-result rendering in `CourseDetail`.
- `sub-components/create-course`, `create-exam`, `student-list`, `add-students-modal`, `scan-upload-modal`, and `grade-history` are opened or embedded by the page.
- `components/template-builder`, `answer-key`, and `dashboard-regrade-requests-card` are embedded workflows whose outputs refresh course state.
- Notification links may arrive as `/courses?courseId=...&examId=...`; `components/courses` converts these to `/courses/:id`, and `CourseDetail` opens the requested exam action after loading.

Backend changes to course responses, course statistics, comparison responses, exam statistics, grading-result sections, archive behavior, or authorization can all affect this page. Relevant routes are under `/api/courses`, `/api/exams`, `/api/exam-templates`, `/api/grading`, and `/api/review-requests`.

## Refactor rules

- Preserve the visible section order: header, jump navigation, overview, exams, then students, followed by route-level modals.
- Preserve deep links, refresh callbacks, and `afterNextRender` chart initialization when extracting UI.
- Keep API ownership in the component that owns the complete workflow. Presentational components should use inputs and outputs.
- Move component-specific CSS with extracted markup so the parent stylesheet does not retain dead selectors.
- Update `course-detail.spec.ts` for route-level integration and add focused specs beside extracted components for their local behavior.
