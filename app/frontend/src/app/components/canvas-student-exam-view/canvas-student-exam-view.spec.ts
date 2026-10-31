import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { CanvasService } from '../../services/canvas.service';
import { CanvasStudentExamView } from './canvas-student-exam-view';


const grade = {
  id: 'grade-id',
  omr_marking_id: 'marking-id',
  exam_answer_key_id: 'answer-key-id',
  question_results: {},
  total_score: 8,
  max_score: 10,
  template_version: 1,
  exam_version: null,
  student_id: 'student-id',
  status: 'graded',
  flag_reason: null,
  graded_at: '2026-07-24T00:00:00Z',
  section_results: [],
  page_count: 1,
  exam_id: 'exam-id',
};

const emptyIdentity = {
  fields: [],
  last_name: '',
  first_name: '',
  student_id: '',
  page_index: null,
};

describe('CanvasStudentExamView', () => {
  let fixture: ComponentFixture<CanvasStudentExamView>;
  let canvasService: {
    getStudentResult: ReturnType<typeof vi.fn>;
    getStudentResultIdentity: ReturnType<typeof vi.fn>;
    getStudentResultPageAnnotations: ReturnType<typeof vi.fn>;
    getStudentResultPageIdentity: ReturnType<typeof vi.fn>;
    getStudentResultPageVersion: ReturnType<typeof vi.fn>;
    getStudentResultPageImage: ReturnType<typeof vi.fn>;
  };
  let navigate: ReturnType<typeof vi.fn>;

  function configure(fragment: string | null): void {
    canvasService = {
      getStudentResult: vi.fn().mockReturnValue(of(grade)),
      getStudentResultIdentity: vi.fn().mockReturnValue(of(emptyIdentity)),
      getStudentResultPageAnnotations: vi.fn().mockReturnValue(of([])),
      getStudentResultPageIdentity: vi.fn().mockReturnValue(of(emptyIdentity)),
      getStudentResultPageVersion: vi
        .fn()
        .mockReturnValue(of({ field: null, detected_version: null })),
      getStudentResultPageImage: vi
        .fn()
        .mockReturnValue(of(new Blob(['page'], { type: 'image/jpeg' }))),
    };
    navigate = vi.fn().mockResolvedValue(true);

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn().mockReturnValue('blob:student-result-page'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });

    TestBed.configureTestingModule({
      imports: [CanvasStudentExamView],
      providers: [
        { provide: CanvasService, useValue: canvasService },
        { provide: ActivatedRoute, useValue: { snapshot: { fragment } } },
        { provide: Router, useValue: { navigate } },
      ],
    });
    fixture = TestBed.createComponent(CanvasStudentExamView);
  }

  afterEach(() => TestBed.resetTestingModule());

  it('reads the token from the URL fragment and removes it from the address bar', () => {
    configure('token=student-result-token');

    fixture.detectChanges();

    expect(canvasService.getStudentResult).toHaveBeenCalledWith('student-result-token');
    expect(canvasService.getStudentResultPageImage).toHaveBeenCalledWith(
      'student-result-token',
      0,
    );
    expect(navigate).toHaveBeenCalledWith([], {
      relativeTo: TestBed.inject(ActivatedRoute),
      fragment: undefined,
      replaceUrl: true,
    });
    expect(fixture.componentInstance.grade()?.id).toBe('grade-id');
    expect(fixture.componentInstance.imageUrl()).toBe('blob:student-result-page');
  });

  it('does not call the backend when the Canvas link has no token', () => {
    configure(null);

    fixture.detectChanges();

    expect(canvasService.getStudentResult).not.toHaveBeenCalled();
    expect(fixture.componentInstance.error()).toContain('invalid or has expired');
  });

  it('shows the same generic error when token redemption is rejected', () => {
    configure('token=invalid-token');
    canvasService.getStudentResult.mockReturnValue(
      throwError(() => new Error('unauthorized')),
    );

    fixture.detectChanges();

    expect(fixture.componentInstance.grade()).toBeNull();
    expect(fixture.componentInstance.error()).toContain('invalid or has expired');
  });
});
