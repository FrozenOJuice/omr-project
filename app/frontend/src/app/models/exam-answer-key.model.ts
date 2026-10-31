// TS mirror of app/backend/schemas/exam_answer_keys.py.
// An answer key belongs to an exam: one unversioned key when n_versions is 1,
// otherwise one key for each configured version letter.
// and fills in a template's question shape with the correct choices and
// grading rules. answer_key is keyed by question index as a string.

export type GradingType = 'single' | 'multiple' | 'partial';

export interface AnswerKeyItem {
  grading_type: GradingType;
  correct_choices: string[];
  points?: number | null;
  // Required when grading_type is 'partial'; must be null/absent for 'single'.
  partial_weights?: Record<string, number> | null;
}

export interface CreateExamAnswerKeyRequest {
  exam_template_id: string;
  exam_version?: string | null; // null for one version; otherwise a configured A-Z letter
  answer_key: Record<string, AnswerKeyItem>;
  scoring_rules?: Record<string, number> | null;
}

export interface UpdateExamAnswerKeyRequest {
  answer_key?: Record<string, AnswerKeyItem>;
  scoring_rules?: Record<string, number> | null;
}

export interface ExamAnswerKeyResponse {
  id: string;
  exam_id: string;
  exam_template_id: string | null;
  exam_version: string | null;
  answer_key: Record<string, AnswerKeyItem>;
  scoring_rules: Record<string, number> | null;
  answer_key_path: string | null;
  created_at: string;
}

export interface ExtractAnswerKeyScanBatchRequest {
  // The PDF is the `file` part of FormData; this is its accompanying metadata.
  question_count: number;
}

export type AnswerKeyScanWarningCode =
  | 'blank_answer'
  | 'low_confidence'
  | 'version_not_detected'
  | 'version_ambiguous'
  | 'version_invalid'
  | 'version_duplicate';

export interface ExtractedAnswerKeyQuestion {
  selected_choices: string[];
  confidence: number;
  flagged: boolean;
}

export interface AnswerKeyScanWarning {
  code: AnswerKeyScanWarningCode;
  message: string;
  question_id: string | null;
  selected_choices: string[];
  confidence: number | null;
}

export type AnswerKeyVersionDetectionStatus =
  | 'detected'
  | 'missing'
  | 'ambiguous'
  | 'not_applicable';

export interface AnswerKeyVersionDetection {
  status: AnswerKeyVersionDetectionStatus;
  selected_choices: string[];
  detected_version: string | null;
  confidence: number | null;
}

export interface ExtractedAnswerKeySheet {
  sheet_index: number;
  source_filename: string;
  page_start: number;
  page_end: number;
  answers: Record<string, ExtractedAnswerKeyQuestion>;
  version: AnswerKeyVersionDetection;
  minimum_confidence: number | null;
  warnings: AnswerKeyScanWarning[];
}

export interface ExtractAnswerKeyScanBatchResponse {
  pages_per_sheet: number;
  sheets: ExtractedAnswerKeySheet[];
}

export type AnswerKeyScanMatchingMode = 'automatic' | 'ordered' | 'manual';
export type AnswerKeyScanMatchAction = 'apply' | 'skip';

export interface AnswerKeyScanSheetMatch {
  sheet_index: number;
  action: AnswerKeyScanMatchAction;
  target_version: string | null;
}

export interface ConfirmAnswerKeyScanMatchesRequest {
  matching_mode: AnswerKeyScanMatchingMode;
  matches: AnswerKeyScanSheetMatch[];
  overwrite_existing: boolean;
}
