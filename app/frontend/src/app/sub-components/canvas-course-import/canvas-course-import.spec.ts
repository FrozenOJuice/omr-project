import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { CanvasCourseImportResponse } from '../../models/canvas.model';
import { ApiCourse } from '../../models/course.model';
import { CanvasService } from '../../services/canvas.service';
import { CanvasCourseImport } from './canvas-course-import';

describe('CanvasCourseImport', () => {
  let fixture: ComponentFixture<CanvasCourseImport>;
  let component: CanvasCourseImport;

  const course = {
    id: '9007199254740993',
    name: 'Integration Test Course',
    course_code: 'CANVAS 101',
    imported: false,
    omr_course_id: null,
  };
  const secondCourse = {
    id: '9007199254740994',
    name: 'Second Integration Course',
    course_code: 'CANVAS 102',
    imported: false,
    omr_course_id: null,
  };
  const canvasService = {
    getCourses: vi.fn(() => of([course, secondCourse])),
    getRoster: vi.fn(() =>
      of({
        course_id: '9007199254740993',
        skip_reasons: {},
        students: [
          {
            id: '9007199254740995',
            name: 'Student Example',
            login_id: 'student@example.com',
            sis_user_id: '12345678',
          },
        ],
      }),
    ),
    importCourses: vi.fn((ids: string[]) =>
      of<CanvasCourseImportResponse>({
        results: ids.map((id) => ({
          canvas_course_id: id,
          status: 'imported' as const,
          course: { id: `omr-course-${id}` } as ApiCourse,
          roster_sync: null,
          message: null,
        })),
      }),
    ),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    await TestBed.configureTestingModule({
      imports: [CanvasCourseImport],
      providers: [provideRouter([]), { provide: CanvasService, useValue: canvasService }],
    }).compileComponents();
    fixture = TestBed.createComponent(CanvasCourseImport);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('previews a roster without selecting the course for import', () => {
    component.previewCourseRoster(course);

    expect(canvasService.getRoster).toHaveBeenCalledWith('9007199254740993');
    expect(component.students[0].name).toBe('Student Example');
    expect(component.isSelected('9007199254740993')).toBe(false);
  });

  it('only toggles import selection through the checkbox action', () => {
    component.toggleSelection(course);

    expect(component.isSelected(course.id)).toBe(true);
    expect(canvasService.getRoster).not.toHaveBeenCalled();
  });

  it('imports and emits multiple selected courses', () => {
    const emitted = vi.fn();
    component.imported.subscribe(emitted);
    component.toggleSelection(course);
    component.toggleSelection(secondCourse);

    component.importCourses();

    expect(canvasService.importCourses).toHaveBeenCalledWith([
      '9007199254740993',
      '9007199254740994',
    ]);
    expect(emitted).toHaveBeenCalledWith({
      courses: [{ id: 'omr-course-9007199254740993' }, { id: 'omr-course-9007199254740994' }],
      complete: true,
    });
  });

  it('keeps failed courses selected and reports partial imports', () => {
    canvasService.importCourses.mockReturnValue(
      of<CanvasCourseImportResponse>({
        results: [
          {
            canvas_course_id: course.id,
            status: 'imported' as const,
            course: { id: 'omr-course-1' } as ApiCourse,
            roster_sync: null,
            message: null,
          },
          {
            canvas_course_id: secondCourse.id,
            status: 'failed' as const,
            course: null,
            roster_sync: null,
            message: 'Canvas course could not be read.',
          },
        ],
      }),
    );
    const emitted = vi.fn();
    component.imported.subscribe(emitted);
    component.toggleSelection(course);
    component.toggleSelection(secondCourse);

    component.importCourses();

    expect(component.isSelected(course.id)).toBe(false);
    expect(component.isSelected(secondCourse.id)).toBe(true);
    expect(component.error).toContain('Some courses');
    expect(emitted).toHaveBeenCalledWith({
      courses: [{ id: 'omr-course-1' }],
      complete: false,
    });
  });
});
