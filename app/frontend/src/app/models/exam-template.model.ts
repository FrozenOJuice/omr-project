// TS mirror of app/backend/schemas/exam_templates.py.
// A template is a reusable bubble-sheet layout (name + question structure).
// It carries NO answer key or scoring — those live on the exam's answer keys
// (see exam-answer-key.model.ts). question_config is keyed by the question
// index as a string ('1', '2', ...).

export interface QuestionConfigItem {
  choices: string[]; // at least 2, e.g. ['A', 'B', 'C', 'D', 'E']
}

export type TemplateSectionType = 'multiple_choice' | 'true_false';

export interface TemplateSection {
  id: string;
  name: string;
  type: TemplateSectionType;
  question_ids: string[];
}

export interface CreateExamTemplateRequest {
  name: string;
  question_config: Record<string, QuestionConfigItem>;
  version?: number | null;
  n_versions?: number; // 1-26, backend default 4
  sections?: TemplateSection[];
}

export interface UpdateExamTemplateRequest {
  name?: string;
  question_config?: Record<string, QuestionConfigItem>;
  n_versions?: number;
  sections?: TemplateSection[];
}

export interface ExamTemplateResponse {
  id: string;
  name: string;
  created_by: string | null;
  question_config: Record<string, QuestionConfigItem>;
  total_questions: number;
  version: number;
  n_versions: number;
  blueprint: string | null; // e.g. 'ubco_100' — fixed hand-made physical sheet, not custom-drawn
  version_from_q1: boolean; // ubco_100 only: Q1 is the version selector, not a graded question
  omr_template_id: string | null;
  generated_pdf_path: string | null;
  archived_at: string | null;
  sections: TemplateSection[];
}

export interface ExamTemplateUsageExam {
  id: string;
  name: string;
  course_id: string;
  answer_key_count: number;
  scan_count: number;
}

export interface ExamTemplateUsageResponse {
  template_id: string;
  exam_count: number;
  answer_key_count: number;
  scan_count: number;
  exams: ExamTemplateUsageExam[];
}
