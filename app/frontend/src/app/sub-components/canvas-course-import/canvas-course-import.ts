import { ChangeDetectorRef, Component, EventEmitter, OnInit, Output, inject } from '@angular/core';
import { Router } from '@angular/router';
import { ApiCourse } from '../../models/course.model';
import {
  CanvasCourse,
  CanvasCourseImportResult,
  CanvasStudent,
  canvasRosterSkipSummary,
} from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';
import { extractApiErrorMessage } from '../../utils/api-error';

const MAX_COURSE_IMPORTS = 25;

@Component({
  selector: 'app-canvas-course-import',
  templateUrl: './canvas-course-import.html',
  styleUrl: './canvas-course-import.css',
})
export class CanvasCourseImport implements OnInit {
  @Output() close = new EventEmitter<void>();
  @Output() imported = new EventEmitter<{ courses: ApiCourse[]; complete: boolean }>();

  private canvasService = inject(CanvasService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  courses: CanvasCourse[] = [];
  students: CanvasStudent[] = [];
  selectedCourseIds = new Set<string>();
  previewCourseId: string | null = null;
  loadingCourses = true;
  loadingRoster = false;
  importing = false;
  error = '';
  rosterError = '';
  rosterSkipReasons: Record<string, number> = {};
  importResults: CanvasCourseImportResult[] = [];

  get selectedCourses(): CanvasCourse[] {
    return this.courses.filter((course) => this.selectedCourseIds.has(course.id));
  }

  get previewCourse(): CanvasCourse | null {
    return this.courses.find((course) => course.id === this.previewCourseId) ?? null;
  }

  get rosterSkipCount(): number {
    return Object.values(this.rosterSkipReasons).reduce((total, count) => total + count, 0);
  }

  get rosterSkipSummary(): string {
    return canvasRosterSkipSummary(this.rosterSkipReasons);
  }

  ngOnInit(): void {
    this.canvasService.getCourses().subscribe({
      next: (courses) => {
        this.courses = courses;
        this.loadingCourses = false;
        this.cdr.markForCheck();
      },
      error: (error) => {
        this.error = extractApiErrorMessage(error, 'Connected courses could not be loaded.');
        this.loadingCourses = false;
        this.cdr.markForCheck();
      },
    });
  }

  toggleSelection(course: CanvasCourse): void {
    if (this.importing) return;
    if (course.imported) return;

    const selected = new Set(this.selectedCourseIds);
    if (selected.has(course.id)) {
      selected.delete(course.id);
    } else if (selected.size < MAX_COURSE_IMPORTS) {
      selected.add(course.id);
    } else {
      this.error = `Import up to ${MAX_COURSE_IMPORTS} courses at a time.`;
    }
    this.selectedCourseIds = selected;
  }

  previewCourseRoster(course: CanvasCourse): void {
    if (this.importing) return;
    this.previewCourseId = course.id;

    this.students = [];
    this.rosterSkipReasons = {};
    this.rosterError = '';
    this.loadingRoster = true;
    this.canvasService.getRoster(course.id).subscribe({
      next: (roster) => {
        if (this.previewCourseId !== course.id) return;
        this.students = roster.students;
        this.rosterSkipReasons = roster.skip_reasons;
        this.loadingRoster = false;
        this.cdr.markForCheck();
      },
      error: (error) => {
        if (this.previewCourseId !== course.id) return;
        this.rosterError = extractApiErrorMessage(error, 'This course roster could not be loaded.');
        this.loadingRoster = false;
        this.cdr.markForCheck();
      },
    });
  }

  isSelected(courseId: string): boolean {
    return this.selectedCourseIds.has(courseId);
  }

  importCourses(): void {
    const courses = this.selectedCourses;
    if (!courses.length || this.importing) return;
    this.importing = true;
    this.error = '';
    this.importResults = [];
    this.canvasService.importCourses(courses.map((course) => course.id)).subscribe({
      next: (response) => {
        this.importing = false;
        this.importResults = response.results;
        const imported = response.results
          .filter((result) => result.status === 'imported' && result.course)
          .map((result) => result.course as ApiCourse);
        const resolvedIds = new Set(
          response.results
            .filter((result) => result.status !== 'failed')
            .map((result) => result.canvas_course_id),
        );
        this.courses = this.courses.map((course) =>
          resolvedIds.has(course.id)
            ? {
                ...course,
                imported: true,
                omr_course_id:
                  response.results.find((result) => result.canvas_course_id === course.id)?.course
                    ?.id ?? course.omr_course_id,
              }
            : course,
        );
        this.selectedCourseIds = new Set(
          [...this.selectedCourseIds].filter((id) => !resolvedIds.has(id)),
        );
        const complete = response.results.every((result) => result.status !== 'failed');
        if (!complete) this.error = 'Some courses could not be imported. Review the results below.';
        if (imported.length || complete) this.imported.emit({ courses: imported, complete });
        this.cdr.markForCheck();
      },
      error: (error) => {
        this.importing = false;
        this.error = extractApiErrorMessage(error, 'One or more courses could not be imported.');
        this.cdr.markForCheck();
      },
    });
  }

  openCourse(): void {
    const courseId = this.previewCourse?.omr_course_id;
    if (courseId) this.router.navigate(['/courses', courseId]);
  }
}
