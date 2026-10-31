import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { GradeHistory } from './grade-history';
import { ExamReleaseAuditEntry, GradeAuditEntry } from '../../models/exam.model';
import { ExamService } from '../../services/exam.service';

const makeEntry = (overrides: Partial<GradeAuditEntry> = {}): GradeAuditEntry => ({
  id: 'entry-1',
  exam_grade_id: 'grade-1',
  actor_user_id: null,
  actor_name: null,
  event_type: 'initial_grade',
  previous_total_score: null,
  new_total_score: 4,
  changes: {},
  created_at: '2026-07-01T09:00:00Z',
  ...overrides,
});

const makeReleaseEntry = (overrides: Partial<ExamReleaseAuditEntry> = {}): ExamReleaseAuditEntry => ({
  id: 'release-1',
  exam_id: 'exam-1',
  actor_user_id: null,
  actor_name: 'Prof Example',
  event_type: 'released',
  created_at: '2026-07-01T09:00:00Z',
  ...overrides,
});

describe('GradeHistory', () => {
  let component: GradeHistory;
  let fixture: ComponentFixture<GradeHistory>;
  const mockExamService = {
    getGradeHistory: vi.fn(() => of([] as GradeAuditEntry[])),
    getReleaseHistory: vi.fn(() => of([] as ExamReleaseAuditEntry[])),
  };

  beforeEach(async () => {
    mockExamService.getGradeHistory.mockReturnValue(of([]));
    mockExamService.getReleaseHistory.mockReturnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [GradeHistory],
      providers: [{ provide: ExamService, useValue: mockExamService }],
    }).compileComponents();

    fixture = TestBed.createComponent(GradeHistory);
    component = fixture.componentInstance;
    component.gradeId = 'grade-1';
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('loads and reverses history so the newest entry is first', () => {
    const initial = makeEntry({ id: 'a', event_type: 'initial_grade', new_total_score: 4 });
    const correction = makeEntry({
      id: 'b',
      event_type: 'manual_correction',
      previous_total_score: 4,
      new_total_score: 3,
      actor_name: 'Prof Example',
      changes: { questions: { '1': { before: null, after: null } as any } },
      created_at: '2026-07-02T09:00:00Z',
    });
    mockExamService.getGradeHistory.mockReturnValue(of([initial, correction]));

    fixture.detectChanges();

    expect(component.rows().length).toBe(2);
    expect(component.rows()[0].id).toBe('b');
    expect(component.rows()[1].id).toBe('a');
    expect(component.loading()).toBe(false);
  });

  it('labels the initial entry as automated grading when there is no actor', () => {
    mockExamService.getGradeHistory.mockReturnValue(of([makeEntry()]));
    fixture.detectChanges();
    expect(component.rows()[0].actorLabel).toBe('Automated grading');
    expect(component.rows()[0].summary).toBe('Initial automated grade');
  });

  it('labels an anonymized manual correction as course staff', () => {
    mockExamService.getGradeHistory.mockReturnValue(of([makeEntry({
      event_type: 'manual_correction',
      previous_total_score: 4,
      new_total_score: 3,
      changes: { questions: { '1': { before: null, after: null } as any } },
    })]));

    fixture.detectChanges();

    expect(component.rows()[0].actorLabel).toBe('Course staff');
  });

  it('summarizes a flag-only resolution with no answer changes', () => {
    const entry = makeEntry({
      event_type: 'manual_correction',
      actor_name: 'Prof Example',
      previous_total_score: 4,
      new_total_score: 4,
      changes: { status: { before: 'needs_review', after: 'graded' } },
    });
    mockExamService.getGradeHistory.mockReturnValue(of([entry]));
    fixture.detectChanges();
    expect(component.rows()[0].summary).toBe('Flag resolved (no answers changed)');
  });

  it('summarizes corrected questions', () => {
    const entry = makeEntry({
      event_type: 'manual_correction',
      actor_name: 'Prof Example',
      previous_total_score: 2,
      new_total_score: 1,
      changes: { questions: { '3': { before: null, after: null } as any, '1': { before: null, after: null } as any } },
    });
    mockExamService.getGradeHistory.mockReturnValue(of([entry]));
    fixture.detectChanges();
    expect(component.rows()[0].summary).toBe('Corrected Q1, Q3');
    expect(component.rows()[0].scoreLabel).toBe('2 to 1');
  });

  it('re-resolves the assigned student name once the roster arrives after history has already loaded', () => {
    const entry = makeEntry({
      event_type: 'manual_correction',
      actor_name: 'Prof Example',
      previous_total_score: 0,
      new_total_score: 4,
      changes: { student_id: { before: null, after: 'user-1' } },
    });
    mockExamService.getGradeHistory.mockReturnValue(of([entry]));

    // History resolves before the roster does (the real-world race: courses.ts
    // fires getCourseStudents and listExamGrades independently).
    fixture.detectChanges();
    expect(component.rows()[0].summary).toBe('Reassigned to user-1');

    fixture.componentRef.setInput('roster', [
      { id: 's1', userId: 'user-1', firstName: 'Jane', lastName: 'Doe', email: 'jane@example.com', studentNumber: '123', accountStatus: 'linked' as const, source: 'manual', active: true },
    ]);
    fixture.detectChanges();

    expect(component.rows()[0].summary).toBe('Reassigned to Jane Doe');
  });

  it('sets an error message when the request fails', () => {
    mockExamService.getGradeHistory.mockReturnValue(throwError(() => new Error('nope')));
    fixture.detectChanges();
    expect(component.error()).toBe('Unable to load history for this grade.');
    expect(component.loading()).toBe(false);
  });

  it('does not fetch release history when no examId is given', () => {
    fixture.detectChanges();
    expect(mockExamService.getReleaseHistory).not.toHaveBeenCalled();
  });

  it('interleaves release events with grade events in newest-first order', () => {
    component.examId = 'exam-1';
    mockExamService.getGradeHistory.mockReturnValue(of([
      makeEntry({ id: 'grade-a', created_at: '2026-07-01T09:00:00Z' }),
      makeEntry({ id: 'grade-b', created_at: '2026-07-03T09:00:00Z', event_type: 'manual_correction', actor_name: 'Prof Example', previous_total_score: 4, new_total_score: 3 }),
    ]));
    mockExamService.getReleaseHistory.mockReturnValue(of([
      makeReleaseEntry({ id: 'release-a', created_at: '2026-07-02T09:00:00Z', event_type: 'released' }),
    ]));

    fixture.detectChanges();

    expect(mockExamService.getReleaseHistory).toHaveBeenCalledWith('exam-1');
    expect(component.rows().map((row) => row.id)).toEqual(['grade-b', 'release-a', 'grade-a']);
    expect(component.rows()[1].kind).toBe('release');
    expect(component.rows()[1].summary).toBe('Released exam results');
    expect(component.rows()[1].scoreLabel).toBeNull();
  });

  it('labels an unreleased event and falls back to "Unknown user" without an actor', () => {
    component.examId = 'exam-1';
    mockExamService.getReleaseHistory.mockReturnValue(of([
      makeReleaseEntry({ event_type: 'closed', actor_name: null }),
    ]));

    fixture.detectChanges();

    expect(component.rows()[0].summary).toBe('Unreleased exam results');
    expect(component.rows()[0].actorLabel).toBe('Unknown user');
  });

  it('still shows grade history if the release history fetch fails', () => {
    component.examId = 'exam-1';
    mockExamService.getGradeHistory.mockReturnValue(of([makeEntry()]));
    mockExamService.getReleaseHistory.mockReturnValue(throwError(() => new Error('nope')));

    fixture.detectChanges();

    expect(component.error()).toBe('');
    expect(component.rows().length).toBe(1);
  });
});
