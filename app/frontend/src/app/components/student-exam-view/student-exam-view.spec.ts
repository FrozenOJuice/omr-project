import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { StudentExamView } from './student-exam-view';
import { ExamService } from '../../services/exam.service';
import { ReviewRequestService } from '../../services/review-request.service';
import { ExamGrade, ExamScoreDistribution, QuestionAnnotation } from '../../models/exam.model';
import { ApiStudentReviewRequest } from '../../models/regrade-requests.model';

const MOCK_QUESTION_RESULT = {
  grading_type: 'single',
  student_answers: [] as string[],
  correct_answers: ['A'],
  correct: false,
  score: 0,
  max_score: 4,
  ambiguous: false,
};

const MOCK_GRADE: ExamGrade = {
  id: 'g1',
  omr_marking_id: 'omr-1',
  exam_answer_key_id: 'key-1',
  question_results: {
    '1': { ...MOCK_QUESTION_RESULT, max_score: 4 },
    '2': { ...MOCK_QUESTION_RESULT, max_score: 2 },
  },
  total_score: 15,
  max_score: 20,
  template_version: 1,
  exam_version: null,
  student_id: 's1',
  status: 'graded',
  flag_reason: null,
  graded_at: '2026-03-14T00:00:00Z',
  section_results: [],
  page_count: 1,
  exam_id: 'exam-1',
};

const MOCK_PAGE_ANNOTATIONS: QuestionAnnotation[] = [];

describe('StudentExamView', () => {
  let component: StudentExamView;
  let fixture: ComponentFixture<StudentExamView>;

  const mockExamService = {
    getGrade: vi.fn(() => of(MOCK_GRADE)),
    getGradePageAnnotations: vi.fn(() => of(MOCK_PAGE_ANNOTATIONS)),
    getGradePageIdentity: vi.fn(() => of(null)),
    getGradePageVersion: vi.fn(() => of(null)),
    getGradePageImage: vi.fn(() => of(new Blob())),
    getGradeIdentity: vi.fn(() => of(null)),
    getExam: vi.fn(() => of({ course_id: 'course-1' })),
    getExamScoreDistribution: vi.fn(() => of<ExamScoreDistribution | null>(null)),
  };

  const mockReviewRequestService = {
    createReviewRequest: vi.fn(() => of([])),
    listMyReviewRequests: vi.fn(() => of([] as ApiStudentReviewRequest[])),
  };

  beforeEach(async () => {
    Object.values(mockExamService).forEach((fn) => fn.mockClear());
    mockExamService.getGrade.mockReturnValue(of(MOCK_GRADE));
    mockExamService.getGradePageAnnotations.mockReturnValue(of(MOCK_PAGE_ANNOTATIONS));
    mockExamService.getGradePageIdentity.mockReturnValue(of(null));
    mockExamService.getGradePageVersion.mockReturnValue(of(null));
    mockExamService.getGradePageImage.mockReturnValue(of(new Blob()));
    mockExamService.getGradeIdentity.mockReturnValue(of(null));
    mockExamService.getExam.mockReturnValue(of({ course_id: 'course-1' }));
    mockExamService.getExamScoreDistribution.mockReturnValue(of<ExamScoreDistribution | null>(null));
    mockReviewRequestService.createReviewRequest.mockClear();
    mockReviewRequestService.createReviewRequest.mockReturnValue(of([]));
    mockReviewRequestService.listMyReviewRequests.mockClear();
    mockReviewRequestService.listMyReviewRequests.mockReturnValue(of([]));

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:preview'),
    });

    await TestBed.configureTestingModule({
      imports: [StudentExamView],
      providers: [
        { provide: ExamService, useValue: mockExamService },
        { provide: ReviewRequestService, useValue: mockReviewRequestService },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => 'g1' } } },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(StudentExamView);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and load the grade', () => {
    expect(component).toBeTruthy();
    expect(component.grade()?.id).toBe('g1');
  });

  it('should display the student grade as a percentage with the raw score as supporting detail', () => {
    expect(component.percentage()).toBe(75);

    const summary = fixture.nativeElement.querySelector('app-score-summary') as HTMLElement;
    expect(summary.querySelector('.stat-value')?.textContent?.trim()).toBe('75%');
    expect(summary.querySelector('.stat-detail')?.textContent?.trim()).toBe('15/20');
  });

  it('shows the five-number summary and highlights the matching value from the chart', () => {
    mockExamService.getExamScoreDistribution.mockReturnValueOnce(of({
      count: 5,
      min_percentage: 40,
      q1_percentage: 55,
      median_percentage: 70,
      q3_percentage: 82.5,
      max_percentage: 95,
    }));
    component.ngOnInit();
    fixture.detectChanges();

    const points = fixture.nativeElement.querySelectorAll('.boxplot-summary-point');
    const summaryItems = fixture.nativeElement.querySelectorAll('.boxplot-summary-item');
    expect(points).toHaveLength(5);
    expect(summaryItems).toHaveLength(5);
    expect(summaryItems[1].textContent).toContain('Q1');
    expect(summaryItems[1].textContent).toContain('55%');

    points[1].dispatchEvent(new MouseEvent('mouseenter'));
    fixture.detectChanges();

    expect(summaryItems[1].classList).toContain('boxplot-summary-item--active');
  });

  it('should list every question on the grade for the review request form', () => {
    expect(component.reviewQuestionNumbers()).toEqual(['1', '2']);
  });

  it('should exclude questions already graded correct from the review request form', () => {
    mockExamService.getGrade.mockReturnValueOnce(of({
      ...MOCK_GRADE,
      question_results: {
        '1': { ...MOCK_QUESTION_RESULT, max_score: 4, correct: true },
        '2': { ...MOCK_QUESTION_RESULT, max_score: 2, correct: false },
      },
    }));
    component.ngOnInit();

    expect(component.reviewQuestionNumbers()).toEqual(['2']);
  });

  it('should not let a question with an existing pending re-grade request be selected', () => {
    mockReviewRequestService.listMyReviewRequests.mockReturnValueOnce(of([
      {
        id: 'r1',
        exam_grade_id: 'g1',
        student_id: 's1',
        batch_id: null,
        question_number: '1',
        student_comment: null,
        status: 'pending',
        instructor_response: null,
        current_score: 0,
        proposed_score: null,
        proposed_correct: null,
        created_at: '2026-03-14T00:00:00Z',
        resolved_at: null,
      },
    ] as ApiStudentReviewRequest[]));
    component.ngOnInit();

    expect(component.isQuestionPendingReview('1')).toBe(true);
    expect(component.isQuestionPendingReview('2')).toBe(false);

    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');

    expect(component.isReviewRequestQuestionSelected('1')).toBe(false);
  });

  it('should drop a question from the current selection if it became pending before the form was reopened', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.cancelReviewRequest();

    component.pendingReviewQuestions.set(new Set(['1']));
    component.openRequestReviewForm();

    expect(component.isReviewRequestQuestionSelected('1')).toBe(false);
  });

  it('should block submitting when a selected question already has a pending re-grade request', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('2');
    component.reviewRequestExplanation = 'Please review.';
    // Simulates the pending set going stale between selecting the question
    // and submitting (e.g. resolved by staff moments earlier in another tab).
    component.pendingReviewQuestions.set(new Set(['2']));
    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe(
      'Question(s) 2 already have a pending re-grade request.',
    );
    expect(mockReviewRequestService.createReviewRequest).not.toHaveBeenCalled();
  });

  it('should seed a newly-checked question\'s proposed score with its own full max_score', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('2');

    expect(component.isReviewRequestQuestionSelected('2')).toBe(true);
    expect(component.reviewRequestProposedScores()['2']).toBe(2);
  });

  it('should not overwrite an already-entered proposed score when the question is unchecked and rechecked', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.updateReviewRequestProposedScore('1', '1.5');

    component.toggleReviewRequestQuestion('1');
    component.toggleReviewRequestQuestion('1');

    expect(component.reviewRequestProposedScores()['1']).toBe(1.5);
  });

  it('should clamp a typed proposed score to that question\'s own max_score, not another question\'s', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('2');
    component.updateReviewRequestProposedScore('2', '500');

    expect(component.reviewRequestProposedScores()['2']).toBe(2);
  });

  it('should clamp a negative typed proposed score up to 0', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.updateReviewRequestProposedScore('1', '-5');

    expect(component.reviewRequestProposedScores()['1']).toBe(0);
  });

  it('should not zero out the proposed score when the input is cleared or blank', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.updateReviewRequestProposedScore('1', '3');
    component.updateReviewRequestProposedScore('1', '');
    component.updateReviewRequestProposedScore('1', '   ');

    expect(component.reviewRequestProposedScores()['1']).toBe(3);
  });

  it('should report each question\'s own max_score, not the grade total', () => {
    expect(component.reviewRequestMaxScoreFor('1')).toBe(4);
    expect(component.reviewRequestMaxScoreFor('2')).toBe(2);
  });

  it('should require at least one question selected before submitting', () => {
    component.openRequestReviewForm();
    component.reviewRequestExplanation = 'Please review.';
    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe('Select at least one question to review.');
    expect(mockReviewRequestService.createReviewRequest).not.toHaveBeenCalled();
  });

  it('should require an explanation before submitting', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe('Please explain why these questions should be reviewed.');
    expect(mockReviewRequestService.createReviewRequest).not.toHaveBeenCalled();
  });

  it('should submit per-question proposed scores built from each selected question\'s own value', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.toggleReviewRequestQuestion('2');
    component.updateReviewRequestProposedScore('2', '1');
    component.reviewRequestExplanation = 'Q1 fully correct, Q2 partial.';

    component.submitReviewRequest();

    expect(mockReviewRequestService.createReviewRequest).toHaveBeenCalledWith('g1', {
      question_numbers: ['1', '2'],
      student_comment: 'Q1 fully correct, Q2 partial.',
      proposed_scores: { '1': 4, '2': 1 },
    });
  });

  it('should reject a proposed score above that question\'s own max_score at submit time', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('2');
    // Bypasses the input's own clamp to simulate a stale/invalid state.
    component['reviewRequestProposedScores'].set({ '2': 999 });
    component.reviewRequestExplanation = 'Please review.';

    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe('Proposed score for question 2 must be between 0 and 2.');
    expect(mockReviewRequestService.createReviewRequest).not.toHaveBeenCalled();
  });

  it('should clear the form and show a success message after a successful submission', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.reviewRequestExplanation = 'Please review.';

    component.submitReviewRequest();

    expect(component.reviewRequestSuccess()).toBe('Review request submitted.');
    expect(component.reviewRequestQuestions()).toEqual([]);
    expect(component.reviewRequestProposedScores()).toEqual({});
    expect(component.showReviewRequestForm()).toBe(false);
  });

  it('should surface an error and keep the form open when submission fails', () => {
    mockReviewRequestService.createReviewRequest.mockReturnValueOnce(throwError(() => new Error('network error')));
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.reviewRequestExplanation = 'Please review.';

    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe('Unable to submit review request.');
    expect(component.showReviewRequestForm()).toBe(true);
  });

  it('should surface the backend\'s specific error message when submission fails', () => {
    mockReviewRequestService.createReviewRequest.mockReturnValueOnce(throwError(() => ({
      error: { error: { code: 'review_request_already_pending', message: 'Question(s) 1 already have a pending re-grade request' } },
    })));
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.reviewRequestExplanation = 'Please review.';

    component.submitReviewRequest();

    expect(component.reviewRequestError()).toBe('Question(s) 1 already have a pending re-grade request');
  });

  it('should mark the just-submitted questions as pending so they can\'t be immediately re-selected', () => {
    component.openRequestReviewForm();
    component.toggleReviewRequestQuestion('1');
    component.reviewRequestExplanation = 'Please review.';

    component.submitReviewRequest();

    expect(component.isQuestionPendingReview('1')).toBe(true);
  });

  it('should close the form and clear the error on cancel', () => {
    component.openRequestReviewForm();
    component.reviewRequestError.set('some error');
    component.cancelReviewRequest();

    expect(component.showReviewRequestForm()).toBe(false);
    expect(component.reviewRequestError()).toBe('');
  });
});
