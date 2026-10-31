import { ExamStatus } from '../enums/tags.enum';

export const DEFAULT_EXAM_DURATION_MINUTES = 90;
export const EXAM_DURATION_PRESETS = [30, 60, 90, 120, 180] as const;

export interface Exam {
  id: string;
  name: string;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  role: string;
  course_id: string;
  exam_template_id: string | null;
  created_by: string | null;
  created_at: string;
  released: boolean;
  // UI-only fields
  status: ExamStatus;
  scanned: number;
  total: number;
  completedAt: string;
  regradeCount: number;
  ambiguousCount: number;
  hasAnswerKey: boolean;
  answerKeysComplete: boolean;
  templateRegistered: boolean;
  templateMissing: boolean;
  templateWarning: string | null;
  generatedPdfPath: string | null;
  canvasAssignmentId?: string | null;
  canvasAssignmentName?: string | null;
}

export interface ApiExam {
  id: string;
  name: string;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  role: string;
  course_id: string;
  exam_template_id: string | null;
  created_by: string | null;
  created_at: string;
  released: boolean;
  is_graded: boolean;
  // Whether any submission has been graded yet, regardless of whether every
  // scan has been. Unlike is_graded (a "fully graded" completion badge for
  // the course exam list), this is what the answer-key page checks to know
  // whether it should lock editing.
  has_any_grade: boolean;
  has_scans: boolean;
  total_scans: number;
  graded_scans: number;
  failed_scans: number;
  has_answer_key: boolean;
  answer_keys_complete: boolean;
  template_registered: boolean;
  template_missing?: boolean;
  template_warning?: string | null;
  generated_pdf_path?: string | null;
  canvas_assignment_id?: string | null;
  canvas_assignment_name?: string | null;
  pending_review_request_count?: number;
  ambiguous_grade_count?: number;
}

export function apiExamToExam(api: ApiExam): Exam {
  const ambiguousCount = api.ambiguous_grade_count ?? 0;
  return {
    id: api.id,
    name: api.name,
    description: api.description,
    start_time: api.start_time,
    end_time: api.end_time,
    role: api.role,
    course_id: api.course_id,
    exam_template_id: api.exam_template_id,
    created_by: api.created_by,
    created_at: api.created_at,
    released: api.released,
    status: api.is_graded
      ? (ambiguousCount > 0 ? ExamStatus.ReviewRequired : ExamStatus.Graded)
      : api.failed_scans > 0
        ? ExamStatus.ScanFailed
        : api.has_scans
          ? ExamStatus.Processing
          : ExamStatus.UnGraded,
    scanned: api.graded_scans,
    total: api.total_scans,
    completedAt: '',
    regradeCount: api.pending_review_request_count ?? 0,
    ambiguousCount,
    hasAnswerKey: api.has_answer_key,
    answerKeysComplete: api.answer_keys_complete,
    templateRegistered: api.template_registered,
    templateMissing: api.template_missing ?? false,
    templateWarning: api.template_warning ?? null,
    generatedPdfPath: api.generated_pdf_path ?? null,
    canvasAssignmentId: api.canvas_assignment_id ?? null,
    canvasAssignmentName: api.canvas_assignment_name ?? null,
  };
}

// A reason release was refused (a flagged grade or an unprocessed scan) --
// see services/exam.py's get_release_blockers on the backend.
export interface ReleaseBlocker {
  type: 'grade' | 'scan';
  id: string;
  reason: string | null;
}

export interface ExamReleaseAuditEntry {
  id: string;
  exam_id: string;
  actor_user_id: string | null;
  actor_name: string | null;
  event_type: 'released' | 'closed';
  created_at: string;
}

export type DistractorEffectiveness = 'correct' | 'effective' | 'weak' | 'not_selected' | 'blank';

export interface AnswerChoiceStats {
  answer: string;
  selected_count: number;
  selected_percentage: number;
  is_correct: boolean;
  high_group_percentage: number | null;
  low_group_percentage: number | null;
  effectiveness: DistractorEffectiveness;
}

export interface QuestionStats {
  question_number: string;
  graded_count: number;
  correct_count: number;
  correct_percentage: number;
  incorrect_count: number;
  incorrect_percentage: number;
  average_score: number;
  max_score: number;
  selected_distribution: Record<string, number>;
  answer_choices: AnswerChoiceStats[];
  item_difficulty: number;
  discrimination_index: number | null;
  distractor_efficiency: number | null;
}

export interface ExamVersionStats {
  exam_version: string | null;
  graded_count: number;
  mean_percentage: number | null;
  average_item_difficulty: number | null;
  average_discrimination_index: number | null;
  average_distractor_efficiency: number | null;
  difficult_question_count: number;
  low_discrimination_question_count: number;
  weak_distractor_question_count: number;
  question_stats: QuestionStats[];
}

export interface ExamStats {
  exam_id: string;
  graded_count: number;
  mean_score: number | null;
  standard_deviation_score: number | null;
  median_score: number | null;
  mode_scores: number[];
  highest_score?: number | null;
  lowest_score?: number | null;
  mean_percentage: number | null;
  standard_deviation_percentage: number | null;
  min_percentage: number | null;
  q1_percentage: number | null;
  median_percentage: number | null;
  q3_percentage: number | null;
  max_percentage: number | null;
  score_distribution: ScoreDistributionBucket[];
  question_stats: QuestionStats[];
  version_stats: ExamVersionStats[];
}

export interface ScoreDistributionBucket {
  label: string;
  lower_bound: number;
  upper_bound: number;
  count: number;
  percentage: number;
}

// A student-safe view of the class's score spread: just the five-number
// summary and a count, none of the per-question or per-student detail
// ExamStats carries.
export interface ExamScoreDistribution {
  count: number;
  min_percentage: number | null;
  q1_percentage: number | null;
  median_percentage: number | null;
  q3_percentage: number | null;
  max_percentage: number | null;
}

export interface QuestionResult {
  grading_type: string;
  student_answers: string[];
  correct_answers: string[];
  correct: boolean;
  score: number;
  max_score: number;
  ambiguous: boolean;
}

export interface GradeSectionResult {
  id: string;
  name: string;
  type: string | null;
  question_ids: string[];
  score: number;
  max_score: number;
}

export interface ExamGrade {
  id: string;
  omr_marking_id: string;
  exam_answer_key_id: string;
  question_results: Record<string, QuestionResult>;
  total_score: number;
  max_score: number;
  template_version: number;
  exam_version: string | null;
  student_id: string | null;
  status: string;
  flag_reason: string | null;
  graded_at: string;
  section_results: GradeSectionResult[];
  // How many scan pages this grade has, i.e. the valid range for
  // ExamService.getGradePageAnnotations/getGradePageImage. Null if it
  // couldn't be resolved.
  page_count: number | null;
  // Resolved via exam_answer_key_id. Null if it couldn't be resolved.
  exam_id: string | null;
}

// A single option's bubble bounding box, in scan pixel coordinates, selected
// or not.
export interface OptionBox {
  label: string;
  selected: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
}

// Bounding box enclosing every one of a question's bubbles, not just the
// selected ones. Present even for a blank question, unlike OptionBox.
// Meant as a generous hover/click hit-region for the whole question rather
// than something to draw a visible highlight from.
export interface QuestionBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

// Where a question's bubbles sit on one scan page, plus its grade. Backs the
// annotated exam view: a colored box per bubble drawn over the page image.
export interface QuestionAnnotation {
  question_id: string;
  bounds: QuestionBounds;
  boxes: OptionBox[];
  confidence: number;
  correct: boolean;
  ambiguous: boolean;
  score: number;
  max_score: number;
  student_answers: string[];
  correct_answers: string[];
}

// One character column of a name/student-ID bubble field (e.g. the 3rd
// letter of a last name), same shape as a QuestionAnnotation's bounds/boxes.
export interface IdentityFieldAnnotation {
  field_type: string;
  field_index: number;
  bounds: QuestionBounds;
  boxes: OptionBox[];
  confidence: number;
}

// A grade's (or one page's) name/student-ID bubble fields, plus what OMR
// decoded them as.
export interface IdentityAnnotations {
  fields: IdentityFieldAnnotation[];
  last_name: string;
  first_name: string;
  student_id: string;
  // Which page these fields live on. Null if this marking has no identity
  // fields at all (or, for the page-scoped endpoint, none on that page).
  page_index: number | null;
}

// The version-selector bubble on a page, if this template has one and it's
// on this page, plus what OMR decoded it as. Read-only: a wrong version
// picks the wrong answer key for the whole grade, so fixing it means a
// regrade, not just a display correction.
export interface VersionAnnotation {
  field: IdentityFieldAnnotation | null;
  detected_version: string | null;
}

export interface QuestionChange {
  before: QuestionResult | null;
  after: QuestionResult;
}

// One entry in a grade's audit trail: the initial automated grade, or a
// single manual correction (which may bundle answer/student/flag changes).
export interface GradeAuditEntry {
  id: string;
  exam_grade_id: string;
  actor_user_id: string | null;
  actor_name: string | null;
  event_type: 'initial_grade' | 'manual_correction';
  previous_total_score: number | null;
  new_total_score: number;
  changes: {
    questions?: Record<string, QuestionChange>;
    student_id?: { before: string | null; after: string | null };
    status?: { before: string; after: string };
    flag_reason?: { before: string | null; after: string | null };
  };
  created_at: string;
}

// Manual corrections an instructor can apply to a grade (all optional, combinable):
// reassign the scan to a student, override detected answers (re-scored server-side),
// or mark a flagged grade as reviewed.
export interface UpdateGradePayload {
  student_id?: string;
  corrected_answers?: Record<string, string[]>;
  resolve_flag?: boolean;
  confirm_duplicate_assignment?: boolean;
}
