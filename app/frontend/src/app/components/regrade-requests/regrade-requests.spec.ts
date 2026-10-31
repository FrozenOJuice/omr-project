import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute } from '@angular/router';
import { vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { RegradeRequests } from './regrade-requests';
import { ReviewRequestService } from '../../services/review-request.service';
import { UserService } from '../../services/user.service';
import { ExamService } from '../../services/exam.service';
import { ExamPageViewer } from '../../sub-components/exam-page-viewer/exam-page-viewer';
import {
  ApiReviewRequest,
  ApiStudentReviewRequest,
  ReviewRequestAuditEntry,
} from '../../models/regrade-requests.model';
import { ExamGrade, QuestionAnnotation } from '../../models/exam.model';

const MOCK_QUESTION_RESULT = {
  grading_type: 'single',
  student_answers: [] as string[],
  correct_answers: ['A'],
  correct: false,
  score: 0,
  max_score: 20,
  ambiguous: false,
};

const MOCK_GRADE: ExamGrade = {
  id: 'g1',
  omr_marking_id: 'omr-1',
  exam_answer_key_id: 'key-1',
  question_results: {
    '1': { ...MOCK_QUESTION_RESULT },
    '2': { ...MOCK_QUESTION_RESULT },
    '3': { ...MOCK_QUESTION_RESULT },
    '5': { ...MOCK_QUESTION_RESULT },
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

const MOCK_PAGE_ANNOTATIONS: QuestionAnnotation[] = [
  {
    question_id: '2',
    bounds: { x: 0, y: 0, width: 10, height: 10 },
    boxes: [],
    confidence: 1,
    correct: false,
    ambiguous: false,
    score: 0,
    max_score: 5,
    student_answers: [],
    correct_answers: ['A'],
  },
];

const MOCK_REQUESTS: ApiReviewRequest[] = [
  {
    id: 'r1',
    exam_grade_id: 'g1',
    student_id: 's1',
    batch_id: null,
    question_number: '2',
    student_comment: 'I think question 2 was marked incorrectly.',
    status: 'pending',
    instructor_response: null,
    current_score: 15,
    proposed_score: null,
    proposed_correct: null,
    created_at: '2026-03-14T00:00:00Z',
    resolved_at: null,
    student_name: 'John Doe',
    course_id: 'course-1',
    course_code: 'COSC 320',
    term: 'WS1',
    exam_name: 'Midterm 1',
    max_score: 20,
  },
  {
    id: 'r2',
    exam_grade_id: 'g2',
    student_id: 's2',
    batch_id: null,
    question_number: '1',
    student_comment: 'Please recheck.',
    status: 'resolved',
    instructor_response: 'Score stands.',
    current_score: 18,
    proposed_score: 18,
    proposed_correct: true,
    created_at: '2026-03-15T00:00:00Z',
    resolved_at: '2026-03-16T00:00:00Z',
    student_name: 'Bob Iger',
    course_id: 'course-1',
    course_code: 'COSC 320',
    term: 'WS1',
    exam_name: 'Midterm 1',
    max_score: 20,
  },
];

describe('RegradeRequests', () => {
  let component: RegradeRequests;
  let fixture: ComponentFixture<RegradeRequests>;

  const mockReviewRequestService = {
    listReviewRequests: vi.fn(() => of(MOCK_REQUESTS)),
    listMyReviewRequests: vi.fn(() => of([] as ApiStudentReviewRequest[])),
    getReviewRequestHistory: vi.fn(() => of([] as ReviewRequestAuditEntry[])),
    updateReviewRequest: vi.fn(() => of([MOCK_REQUESTS[0]])),
  };

  const mockUserService = {
    isStudent: vi.fn(() => false),
  };

  const mockExamService = {
    getGrade: vi.fn(() => of(MOCK_GRADE)),
    getGradePageAnnotations: vi.fn(() => of(MOCK_PAGE_ANNOTATIONS)),
    getGradePageImage: vi.fn(() => of(new Blob())),
  };

  beforeEach(async () => {
    mockReviewRequestService.listReviewRequests.mockClear();
    mockReviewRequestService.listMyReviewRequests.mockClear();
    mockReviewRequestService.getReviewRequestHistory.mockClear();
    mockReviewRequestService.updateReviewRequest.mockClear();
    mockUserService.isStudent.mockClear();
    mockUserService.isStudent.mockReturnValue(false);
    mockExamService.getGrade.mockClear();
    mockExamService.getGrade.mockReturnValue(of(MOCK_GRADE));
    mockExamService.getGradePageAnnotations.mockClear();
    mockExamService.getGradePageAnnotations.mockReturnValue(of(MOCK_PAGE_ANNOTATIONS));
    mockExamService.getGradePageImage.mockClear();
    mockExamService.getGradePageImage.mockReturnValue(of(new Blob()));

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:preview'),
    });

    await TestBed.configureTestingModule({
      imports: [RegradeRequests],
      providers: [
        { provide: ReviewRequestService, useValue: mockReviewRequestService },
        { provide: UserService, useValue: mockUserService },
        { provide: ExamService, useValue: mockExamService },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: { get: () => null } },
            queryParamMap: of({ get: () => null }),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RegradeRequests);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load requests on init and select the first one', () => {
    expect(component.requests.length).toBe(2);
    expect(component.selectedRequestId).toBe('r1');
    expect(mockReviewRequestService.getReviewRequestHistory).toHaveBeenCalledWith('r1');
  });

  it('should render a list item per request', () => {
    const items = fixture.debugElement.queryAll(By.css('.regrade-list-item'));
    expect(items.length).toBe(2);
  });

  it('should filter by search query', () => {
    component.searchQuery = 'Bob';
    expect(component.filteredRequests.length).toBe(1);
    expect(component.filteredRequests[0].student_name).toBe('Bob Iger');
  });

  it('should filter by status', () => {
    component.selectedStatus = 'resolved';
    expect(component.filteredRequests.length).toBe(1);
    expect(component.filteredRequests[0].id).toBe('r2');
  });

  it('should update selected request on row click', () => {
    component.selectRequest(component.groupedRequests[1]);
    expect(component.selectedRequestId).toBe('r2');
    expect(component.selectedRequest?.student_name).toBe('Bob Iger');
  });

  it('should set previewGradeId to the selected request\'s exam_grade_id', () => {
    expect(component.previewGradeId).toBe('g1');

    component.selectRequest(component.groupedRequests[1]);

    expect(component.previewGradeId).toBe('g2');
    expect(mockExamService.getGrade).toHaveBeenCalledWith('g2');
  });

  it('should pass previewGradeId through to the exam page viewer as gradeId, so it resets zoom on scan switch', () => {
    const viewer = fixture.debugElement.query(By.directive(ExamPageViewer)).componentInstance as ExamPageViewer;
    expect(viewer.gradeId()).toBe('g1');

    component.selectRequest(component.groupedRequests[1]);
    fixture.detectChanges();

    expect(viewer.gradeId()).toBe('g2');
  });

  it('should group rows sharing a batch_id into one request with a combined question label', () => {
    const batched: ApiReviewRequest[] = [
      { ...MOCK_REQUESTS[0], id: 'b1', batch_id: 'batch-1', question_number: '5' },
      { ...MOCK_REQUESTS[0], id: 'b2', batch_id: 'batch-1', question_number: '3' },
    ];
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of(batched));
    component.loadRequests();

    expect(component.groupedRequests.length).toBe(1);
    const group = component.groupedRequests[0];
    // Sorted by question number, not submission order, and represented by
    // the lowest-numbered row (see groupByBatch).
    expect(group.id).toBe('b2');
    expect(group.questionLabel).toBe('Questions 3, 5');
    expect(group.requests.map((r) => r.id)).toEqual(['b2', 'b1']);
  });

  it('should apply a resolved decision to every row in the batch', () => {
    const batched: ApiReviewRequest[] = [
      { ...MOCK_REQUESTS[0], id: 'b1', batch_id: 'batch-1', question_number: '5' },
      { ...MOCK_REQUESTS[0], id: 'b2', batch_id: 'batch-1', question_number: '3' },
    ];
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of(batched));
    component.loadRequests();
    component.selectRequest(component.groupedRequests[0]);
    mockReviewRequestService.updateReviewRequest.mockReturnValueOnce(
      of(batched.map((r) => ({ ...r, status: 'resolved' }))),
    );

    component.confirmResolve();
    component.setDraftProposedCorrect('3', true);
    component.setDraftProposedCorrect('5', true);
    component.updateDraftInstructorResponse('Awarding credit for both questions.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms

    expect(component.requests.every((r) => r.status === 'resolved')).toBe(true);
  });

  it('should load student request history via /api/review-requests/me in student mode', () => {
    mockUserService.isStudent.mockReturnValue(true);
    mockReviewRequestService.listMyReviewRequests.mockReturnValueOnce(of([
      {
        id: 'my-1',
        exam_grade_id: 'g1',
        student_id: 's1',
        batch_id: null,
        question_number: '2',
        student_comment: 'Please review this question.',
        status: 'pending',
        instructor_response: null,
        current_score: 15,
        proposed_score: null,
        proposed_correct: null,
        created_at: '2026-03-14T00:00:00Z',
        resolved_at: null,
      },
    ] as ApiStudentReviewRequest[]));

    component.loadRequests();

    expect(mockReviewRequestService.listMyReviewRequests).toHaveBeenCalled();
    expect(component.filteredMyRequests.length).toBe(1);
    expect(component.filteredMyRequests[0].question_number).toBe('2');
  });

  it('should pre-fill the draft proposed score from what the student originally proposed', () => {
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of([
      { ...MOCK_REQUESTS[0], proposed_score: 12.5 },
      MOCK_REQUESTS[1],
    ]));
    component.loadRequests();

    component.confirmResolve();

    expect(component.draftProposedScore['2']).toBe(12.5);
  });

  it('should leave the draft proposed score blank when the student did not propose one', () => {
    component.confirmResolve();
    expect(component.draftProposedScore['2']).toBeNull();
  });

  it('should send independent proposed_correct/proposed_scores per question in a batch', () => {
    const batched: ApiReviewRequest[] = [
      { ...MOCK_REQUESTS[0], id: 'b1', batch_id: 'batch-1', question_number: '5', current_score: 10, proposed_score: null },
      { ...MOCK_REQUESTS[0], id: 'b2', batch_id: 'batch-1', question_number: '3', current_score: 8, proposed_score: null },
    ];
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of(batched));
    component.loadRequests();
    component.selectRequest(component.groupedRequests[0]);

    component.confirmResolve();
    component.setDraftProposedCorrect('3', true);
    component.setDraftProposedCorrect('5', false);
    component.updateDraftProposedScore('3', '15');
    component.updateDraftInstructorResponse('Q3 gets partial credit, Q5 stays wrong.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms

    expect(mockReviewRequestService.updateReviewRequest).toHaveBeenCalledWith(
      'b2',
      expect.objectContaining({
        proposed_correct: { '3': true, '5': false },
        proposed_scores: { '3': 15, '5': 0 },
      })
    );
  });

  it('should force the proposed score to zero when a question is marked incorrect, even if a value was typed first', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '18');
    component.setDraftProposedCorrect('2', false);

    expect(component.draftProposedScore['2']).toBe(0);
  });

  it('should restore the prior proposed score when a question is switched back to correct', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '18');
    component.setDraftProposedCorrect('2', false);
    expect(component.draftProposedScore['2']).toBe(0);

    component.setDraftProposedCorrect('2', true);
    expect(component.draftProposedScore['2']).toBe(18);
  });

  it('should require a decision for every question in a batch before resolving', () => {
    const batched: ApiReviewRequest[] = [
      { ...MOCK_REQUESTS[0], id: 'b1', batch_id: 'batch-1', question_number: '5' },
      { ...MOCK_REQUESTS[0], id: 'b2', batch_id: 'batch-1', question_number: '3' },
    ];
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of(batched));
    component.loadRequests();
    component.selectRequest(component.groupedRequests[0]);

    component.confirmResolve();
    component.setDraftProposedCorrect('3', true);
    component.updateDraftInstructorResponse('Only decided one of them.');
    component.executeResolve();

    expect(component.resolveError).toBe('Mark question(s) 5 correct or incorrect before resolving.');
    expect(mockReviewRequestService.updateReviewRequest).not.toHaveBeenCalled();
  });

  it('should report the current grade from the fetched grade, not a single question', () => {
    expect(component.currentGradeTotal()).toBe(15);
    expect(component.currentGradeMax()).toBe(20);
  });

  it('should compute the proposed re-grade total from each question\'s own proposed score', () => {
    const batched: ApiReviewRequest[] = [
      { ...MOCK_REQUESTS[0], id: 'b1', batch_id: 'batch-1', question_number: '5', current_score: 10, proposed_score: 15 },
      { ...MOCK_REQUESTS[0], id: 'b2', batch_id: 'batch-1', question_number: '3', current_score: 8, proposed_score: null },
    ];
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of(batched));
    component.loadRequests();
    component.selectRequest(component.groupedRequests[0]);

    // previewGrade.total_score (15) + (proposed - current) per row:
    // question 5: 15 - 10 = +5; question 3 has no proposal, so +0.
    expect(component.proposedGradeTotal(component.groupedRequests[0])).toBe(20);
  });

  it('should return null for the proposed re-grade total before the grade has loaded', () => {
    expect(component.proposedGradeTotal(null)).toBeNull();
  });

  it('should update the confirm pop-up\'s live proposed grade as Correct/Incorrect/score are changed', () => {
    // r1: question 2, current_score 15, max_score 20; previewGrade.total_score 15.
    component.confirmResolve();
    expect(component.draftProposedGradeTotal()).toBe(15); // no decision yet -> no change

    component.setDraftProposedCorrect('2', true);
    expect(component.draftProposedGradeTotal()).toBe(20); // full credit: 15 + (20 - 15)

    component.setDraftProposedCorrect('2', false);
    expect(component.draftProposedGradeTotal()).toBe(0); // zero credit: 15 + (0 - 15)

    component.setDraftProposedCorrect('2', true);
    component.updateDraftProposedScore('2', '12');
    expect(component.draftProposedGradeTotal()).toBe(12); // explicit override: 15 + (12 - 15)
  });

  it('should return null for the confirm pop-up\'s live proposed grade with no request open', () => {
    expect(component.draftProposedGradeTotal()).toBeNull();
  });

  it('should read a question\'s own max_score from the answer key preview, not the grade total', () => {
    expect(component.questionMaxScore('2')).toBe(MOCK_QUESTION_RESULT.max_score);
    expect(component.questionMaxScore('does-not-exist')).toBeNull();
  });

  it('should call updateReviewRequest with resolved status on approve', () => {
    component.confirmResolve();
    component.setDraftProposedCorrect('2', true);
    component.updateDraftInstructorResponse('Partial credit applied.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms
    expect(mockReviewRequestService.updateReviewRequest).toHaveBeenCalledWith(
      'r1',
      expect.objectContaining({
        status: 'resolved',
        instructor_response: 'Partial credit applied.',
        proposed_correct: { '2': true },
      })
    );
  });

  it('should update the instructor response from the confirm pop-up text box', () => {
    const resolveButton = fixture.debugElement.query(By.css('.regrade-resolve-btn'));
    resolveButton.triggerEventHandler('click', null);
    fixture.detectChanges();
    const responseInput = fixture.debugElement.query(By.css('.regrade-response-input'));
    responseInput.nativeElement.value = 'The answer qualifies for partial credit.';
    responseInput.triggerEventHandler('input', { target: responseInput.nativeElement });

    expect(component.draftInstructorResponse).toBe(
      'The answer qualifies for partial credit.'
    );
  });

  it('should open the confirm dialog instead of resolving immediately when the resolve button is clicked', () => {
    const resolveButton = fixture.debugElement.query(By.css('.regrade-resolve-btn'));
    resolveButton.triggerEventHandler('click', null);
    fixture.detectChanges();

    expect(component.confirmingRequest?.id).toBe('r1');
    expect(mockReviewRequestService.updateReviewRequest).not.toHaveBeenCalled();
    expect(fixture.debugElement.query(By.css('.confirm-card'))).toBeTruthy();
  });

  it('should clear the confirm dialog on cancel without resolving', () => {
    component.confirmResolve();
    component.cancelResolve();

    expect(component.confirmingRequest).toBeNull();
    expect(mockReviewRequestService.updateReviewRequest).not.toHaveBeenCalled();
  });

  it('should resolve and close the confirm dialog on confirmed resolve', () => {
    component.confirmResolve();
    component.setDraftProposedCorrect('2', true);
    component.updateDraftInstructorResponse('Awarding credit.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms

    expect(mockReviewRequestService.updateReviewRequest).toHaveBeenCalledWith(
      'r1',
      expect.objectContaining({ status: 'resolved' })
    );
    expect(component.confirmingRequest).toBeNull();
  });

  it('should require marking the question correct or incorrect before resolving', () => {
    component.confirmResolve();
    component.updateDraftInstructorResponse('Looks good.');
    component.executeResolve();

    expect(component.resolveError).toBe('Mark question(s) 2 correct or incorrect before resolving.');
    expect(mockReviewRequestService.updateReviewRequest).not.toHaveBeenCalled();
  });

  it('should require feedback before resolving', () => {
    component.confirmResolve();
    component.setDraftProposedCorrect('2', true);
    component.executeResolve();

    expect(component.resolveError).toBe('Enter feedback for the student before resolving.');
    expect(mockReviewRequestService.updateReviewRequest).not.toHaveBeenCalled();
  });

  it('should render the real empty state (not mock data) when the API returns an empty array', () => {
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of([]));
    component.loadRequests();
    fixture.detectChanges();

    expect(component.requests).toEqual([]);
    expect(component.loadError).toBe(false);
    const emptyTitle = fixture.debugElement.query(By.css('.empty-title'));
    expect(emptyTitle.nativeElement.textContent).toContain('No pending re-grade requests');
  });

  it('should distinguish "no matches" from "no requests" in the empty state when filters are active', () => {
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(of([]));
    component.loadRequests();
    component.searchQuery = 'nobody';
    fixture.detectChanges();

    const emptyTitle = fixture.debugElement.query(By.css('.empty-title'));
    expect(emptyTitle.nativeElement.textContent).toContain('No re-grade requests match your filters');
  });

  it('should show a distinct error banner and no fallback data when the API errors', () => {
    mockReviewRequestService.listReviewRequests.mockReturnValueOnce(throwError(() => new Error('network error')));
    component.loadRequests();
    fixture.detectChanges();

    expect(component.requests).toEqual([]);
    expect(component.loadError).toBe(true);
    expect(fixture.debugElement.query(By.css('.error-toast'))).toBeTruthy();
  });

  it('should dismiss the error banner', () => {
    component.loadError = true;
    component.dismissError();
    expect(component.loadError).toBe(false);
  });

  it('should update the draft proposed score when given a valid number', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '19');
    expect(component.draftProposedScore['2']).toBe(19);
  });

  it('should not zero out the draft proposed score when the input is cleared', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '19');
    component.updateDraftProposedScore('2', '');
    expect(component.draftProposedScore['2']).toBe(19);
  });

  it('should not zero out the draft proposed score when the input is only whitespace', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '19');
    component.updateDraftProposedScore('2', '   ');
    expect(component.draftProposedScore['2']).toBe(19);
  });

  it('should reset the draft fields when the confirm dialog is cancelled', () => {
    component.confirmResolve();
    component.updateDraftInstructorResponse('Some note');
    component.cancelResolve();

    expect(component.draftProposedScore).toEqual({});
    expect(component.draftInstructorResponse).toBe('');
  });

  it('should clamp a typed proposed score above max_score down to max_score', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '500');
    expect(component.draftProposedScore['2']).toBe(20);
  });

  it('should clamp a negative typed proposed score up to 0', () => {
    component.confirmResolve();
    component.updateDraftProposedScore('2', '-20');
    expect(component.draftProposedScore['2']).toBe(0);
  });

  it('should surface a backend rejection instead of silently closing the confirm dialog', () => {
    mockReviewRequestService.updateReviewRequest.mockReturnValueOnce(
      throwError(() => ({ error: { error: { message: 'Proposed score must be between 0 and 20' } } })),
    );
    component.confirmResolve();
    component.setDraftProposedCorrect('2', true);
    component.updateDraftInstructorResponse('Awarding credit.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms

    expect(component.resolveError).toBe('Proposed score must be between 0 and 20');
    // The dialog stays open on failure so the error is visible and the user
    // can correct the input, instead of closing with no feedback.
    expect(component.confirmingRequest).not.toBeNull();
  });

  it('should fall back to a generic message when the backend error has no message field', () => {
    mockReviewRequestService.updateReviewRequest.mockReturnValueOnce(throwError(() => new Error('network error')));
    component.confirmResolve();
    component.setDraftProposedCorrect('2', true);
    component.updateDraftInstructorResponse('Awarding credit.');
    component.executeResolve(); // arms the confirm
    component.executeResolve(); // confirms

    expect(component.resolveError).toBe('Unable to save this decision. Please try again.');
  });

  it('should clear a stale resolveError when the confirm dialog is reopened', () => {
    component.resolveError = 'stale error';
    component.confirmResolve();
    expect(component.resolveError).toBe('');
  });

  it('should show the Proposed Re-grade box for a pending request but hide it once resolved', () => {
    component.selectRequest(component.groupedRequests[0]);
    fixture.detectChanges();
    expect(component.selectedRequest?.status).toBe('pending');
    let labels = Array.from(fixture.nativeElement.querySelectorAll('.regrade-info-label') as NodeListOf<HTMLElement>)
      .map((el) => el.textContent?.trim());
    expect(labels).toContain('Proposed Re-grade');

    component.selectRequest(component.groupedRequests[1]);
    fixture.detectChanges();
    expect(component.selectedRequest?.status).toBe('resolved');
    labels = Array.from(fixture.nativeElement.querySelectorAll('.regrade-info-label') as NodeListOf<HTMLElement>)
      .map((el) => el.textContent?.trim());
    expect(labels).not.toContain('Proposed Re-grade');
  });

  it('should only show the resolve action for pending requests', () => {
    component.selectRequest(component.groupedRequests[1]);
    fixture.detectChanges();

    expect(component.selectedRequest?.status).toBe('resolved');
    expect(fixture.debugElement.query(By.css('.regrade-resolve-btn'))).toBeFalsy();
  });
});
