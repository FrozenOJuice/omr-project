import { ChangeDetectorRef, Component, HostListener, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Course, ApiCourse, apiCourseToCourse, courseBadgeFromCode, formatAcademicPeriod } from '../../models/course.model';
import { apiExamToExam } from '../../models/exam.model';
import { CourseService } from '../../services/course.service';
import { ExamService } from '../../services/exam.service';
import { UserService } from '../../services/user.service';
import { CreateCourse } from '../../sub-components/create-course/create-course';
import { TemplateBuilder } from '../template-builder/template-builder';
import { LoadingSpinner } from '../../sub-components/loading-spinner/loading-spinner';
import { CanvasCourseImport } from '../../sub-components/canvas-course-import/canvas-course-import';
import { CanvasService } from '../../services/canvas.service';
import { forkJoin } from 'rxjs';

@Component({
  selector: 'app-courses',
  imports: [CreateCourse, TemplateBuilder, LoadingSpinner, CanvasCourseImport, FormsModule],
  templateUrl: './courses.html',
  styleUrl: './courses.css',
})
export class Courses implements OnInit {
  readonly formatAcademicPeriod = formatAcademicPeriod;
  readonly courseBadgeFromCode = courseBadgeFromCode;
  private courseService = inject(CourseService);
  private examService = inject(ExamService);
  private canvasService = inject(CanvasService);
  private cdr = inject(ChangeDetectorRef);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly userService = inject(UserService);

  courses: Course[] = [];
  showCreateModal = false;
  showImportModal = false;
  showAddCourseMenu = false;
  canvasConnected = false;
  viewingTemplates = false;
  isLoadingCourses = true;
  coursesLoadError = '';
  searchQuery = '';
  selectedTerm = '';
  archiveFilter: 'active' | 'archived' | 'all' = 'active';
  restoringCourseId: string | null = null;
  restoreUnavailableCourse: Course | null = null;
  confirmingRestoreCourse: Course | null = null;
  showArchiveCleanupConfirmation = false;
  isCleaningArchives = false;
  archiveCleanupNotice = '';

  ngOnInit(): void {
    // Old notification links point at "/courses?courseId=X&examId=Y&action=Z"
    // -- redirect those straight into the course detail page so deep-linking
    // keeps working without any backend changes.
    const params = this.route.snapshot.queryParamMap;
    const courseId = params.get('courseId');
    if (courseId) {
      const queryParams: Record<string, string> = {};
      const examId = params.get('examId');
      const action = params.get('action');
      if (examId) queryParams['examId'] = examId;
      if (action) queryParams['action'] = action;
      this.router.navigate(['/courses', courseId], { queryParams, replaceUrl: true });
      return;
    }

    this.loadCourses();
    if (this.userService.isProfessorOrAbove()) this.loadCanvasConnection();
  }

  loadCourses(): void {
    this.isLoadingCourses = true;
    this.coursesLoadError = '';
    this.courseService.listCourses(this.userService.isProfessorOrAbove()).subscribe({
      next: (apiCourses) => {
        const courses = apiCourses.map(c => apiCourseToCourse(c));
        if (courses.length === 0) {
          this.courses = [];
          this.isLoadingCourses = false;
          this.cdr.markForCheck();
          return;
        }
        forkJoin(courses.map(c => this.examService.listExamsByCourse(c.id))).subscribe({
          next: (examLists) => {
            this.courses = courses.map((c, i) => ({
              ...c,
              exams: examLists[i].map(apiExamToExam),
            }));
            this.isLoadingCourses = false;
            this.cdr.markForCheck();
          },
          error: () => {
            this.coursesLoadError = 'Unable to load exams for your courses.';
            this.isLoadingCourses = false;
            this.cdr.markForCheck();
          },
        });
      },
      error: () => {
        this.coursesLoadError = 'Unable to load courses.';
        this.isLoadingCourses = false;
        this.cdr.markForCheck();
      },
    });
  }

  closeModal(): void {
    this.showCreateModal = false;
  }

  toggleAddCourseMenu(event: MouseEvent): void {
    event.stopPropagation();
    this.showAddCourseMenu = !this.showAddCourseMenu;
  }

  openCreateCourse(): void {
    this.showAddCourseMenu = false;
    this.showCreateModal = true;
  }

  openImportCourse(): void {
    this.showAddCourseMenu = false;
    this.showImportModal = true;
  }

  onCourseCreated(apiCourse: ApiCourse): void {
    this.courses = [{ ...apiCourseToCourse(apiCourse), exams: [], studentList: [], students: 0 }, ...this.courses];
    this.closeModal();
    this.cdr.markForCheck();
  }

  onCoursesImported(result: { courses: ApiCourse[]; complete: boolean }): void {
    const imported = result.courses.map(apiCourse => ({
      ...apiCourseToCourse(apiCourse),
      exams: [],
      studentList: [],
    }));
    this.courses = [...imported, ...this.courses];
    if (result.complete) this.showImportModal = false;
    this.cdr.markForCheck();
  }

  get terms(): string[] {
    return [...new Set(this.courses.map(c => c.academicTerm.name))].sort();
  }

  get filteredCourses(): Course[] {
    const q = this.searchQuery.trim().toLowerCase();
    return this.courses
      .filter(c => {
        const matchesTerm = 
            this.selectedTerm === '' 
            || c.academicTerm.name === this.selectedTerm;
        
        const matchesSearch = 
            q === '' 
            || c.code.toLowerCase().includes(q) 
            || c.name.toLowerCase().includes(q);
        
        const matchesArchive = 
            this.archiveFilter === 'all'
            || (this.archiveFilter === 'archived' && c.archivedAt !== null)
            || (this.archiveFilter !== 'archived' && c.archivedAt === null);
        
        return matchesTerm && matchesSearch && matchesArchive;
      })
      .sort((a, b) => Number(!!a.archivedAt) - Number(!!b.archivedAt));
  }

  promptRestore(course: Course): void {
    if (course.retentionProcessedAt) {
      this.restoreUnavailableCourse = course;
      return;
    }
    if (this.restoringCourseId) return;
    this.confirmingRestoreCourse = course;
  }

  cancelRestore(): void {
    this.confirmingRestoreCourse = null;
  }

  restoreCourse(course: Course): void {
    if (this.restoringCourseId) return;
    this.restoringCourseId = course.id;
    this.coursesLoadError = '';
    this.courseService.restoreCourse(course.id).subscribe({
      next: () => {
        this.courses = this.courses.map(existing =>
          existing.id === course.id ? { ...existing, archivedAt: null } : existing
        );
        this.restoringCourseId = null;
        this.confirmingRestoreCourse = null;
        this.cdr.markForCheck();
      },
      error: (error) => {
        this.restoringCourseId = null;
        this.confirmingRestoreCourse = null;
        this.coursesLoadError = error?.error?.error?.message || 'Unable to restore this course. Please try again.';
        this.cdr.markForCheck();
      },
    });
  }

  cleanupArchives(): void {
    if (!this.userService.isAdmin() || this.isCleaningArchives) return;

    this.isCleaningArchives = true;
    this.coursesLoadError = '';
    this.archiveCleanupNotice = '';
    this.courseService.cleanupArchivedCourses().subscribe({
      next: result => {
        this.isCleaningArchives = false;
        this.showArchiveCleanupConfirmation = false;
        const totalStages = result.scanned_images + result.exam_records;
        this.archiveCleanupNotice = totalStages === 0
          ? 'Archive cleanup finished. No archived courses are currently eligible.'
          : `Archive cleanup finished: ${result.scanned_images} scan-image set(s) and ${result.exam_records} student-record set(s) processed.`;
        this.loadCourses();
        this.cdr.markForCheck();
      },
      error: error => {
        this.isCleaningArchives = false;
        this.coursesLoadError = error?.error?.error?.message
          || 'Unable to clean up archived courses.';
        this.cdr.markForCheck();
      },
    });
  }

  openCourse(course: Course): void {
    this.router.navigate(['/courses', course.id]);
  }

  goToTemplates(): void {
    this.viewingTemplates = true;
  }

  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  closeAddCourseMenu(): void {
    this.showAddCourseMenu = false;
  }

  private loadCanvasConnection(): void {
    this.canvasService.getCapabilities().subscribe({
      next: capability => {
        if (!capability.configured) return;
        this.canvasService.getConnection().subscribe({
          next: connection => {
            this.canvasConnected = connection.connected;
            this.cdr.markForCheck();
          },
          error: () => {
            this.canvasConnected = false;
            this.cdr.markForCheck();
          },
        });
      },
      error: () => {
        this.canvasConnected = false;
        this.cdr.markForCheck();
      },
    });
  }
}
