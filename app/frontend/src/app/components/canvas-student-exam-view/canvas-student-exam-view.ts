import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import {
  ExamGrade,
  IdentityAnnotations,
  QuestionAnnotation,
  VersionAnnotation,
} from '../../models/exam.model';
import { CanvasService } from '../../services/canvas.service';
import {
  ExamPageViewer,
  PositionedBox,
  PositionedRegion,
} from '../../sub-components/exam-page-viewer/exam-page-viewer';
import { ExamResultLayout } from '../../sub-components/exam-result-layout/exam-result-layout';
import { IdentityCard } from '../../sub-components/identity-card/identity-card';
import { QuestionList } from '../../sub-components/question-list/question-list';
import { ScoreSummary } from '../../sub-components/score-summary/score-summary';
import { VersionLabel } from '../../sub-components/version-label/version-label';


@Component({
  selector: 'app-canvas-student-exam-view',
  imports: [
    QuestionList,
    ExamPageViewer,
    ExamResultLayout,
    ScoreSummary,
    IdentityCard,
    VersionLabel,
  ],
  templateUrl: './canvas-student-exam-view.html',
  styleUrl: './canvas-student-exam-view.css',
})
export class CanvasStudentExamView implements OnInit, OnDestroy {
  private canvasService = inject(CanvasService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private accessToken = '';
  private currentObjectUrl: string | null = null;

  grade = signal<ExamGrade | null>(null);
  loadingGrade = signal(true);
  pageCount = computed(() => this.grade()?.page_count ?? 1);
  percentage = computed(() => {
    const grade = this.grade();
    return grade && grade.max_score
      ? Math.round((grade.total_score / grade.max_score) * 1000) / 10
      : null;
  });

  page = signal(0);
  annotations = signal<QuestionAnnotation[]>([]);
  boxes = signal<PositionedBox[]>([]);
  regions = signal<PositionedRegion[]>([]);
  identity = signal<IdentityAnnotations | null>(null);
  gradeIdentity = signal<IdentityAnnotations | null>(null);
  isOnIdentityPage = computed(() => this.page() === this.gradeIdentity()?.page_index);
  version = signal<VersionAnnotation | null>(null);
  imageUrl = signal<string | null>(null);
  loading = signal(false);
  error = signal('');
  hoveredQuestionId = signal<string | null>(null);
  selectedQuestionId = signal<string | null>(null);

  ngOnInit(): void {
    const fragment = new URLSearchParams(this.route.snapshot.fragment ?? '');
    const accessToken = (fragment.get('token') ?? '').trim();
    if (!accessToken) {
      this.failAccess();
      return;
    }

    this.accessToken = accessToken;
    void this.router.navigate([], {
      relativeTo: this.route,
      fragment: undefined,
      replaceUrl: true,
    });
    this.loadResult();
  }

  ngOnDestroy(): void {
    this.accessToken = '';
    this.revokeCurrentUrl();
  }

  prevPage(): void {
    if (this.page() > 0) this.loadPage(this.page() - 1);
  }

  nextPage(): void {
    if (this.page() < this.pageCount() - 1) this.loadPage(this.page() + 1);
  }

  goToIdentityPage(): void {
    const index = this.gradeIdentity()?.page_index;
    if (index == null || index === this.page()) return;
    this.loadPage(index);
  }

  private loadResult(): void {
    this.canvasService.getStudentResult(this.accessToken).subscribe({
      next: (grade) => {
        this.grade.set(grade);
        this.loadingGrade.set(false);
        this.loadIdentity();
        this.loadPage(0);
      },
      error: () => this.failAccess(),
    });
  }

  private loadIdentity(): void {
    this.canvasService.getStudentResultIdentity(this.accessToken).subscribe({
      next: (identity) => this.gradeIdentity.set(identity),
      error: () => {},
    });
  }

  private loadPage(index: number): void {
    this.page.set(index);
    this.loading.set(true);
    this.error.set('');

    forkJoin({
      annotations: this.canvasService.getStudentResultPageAnnotations(
        this.accessToken,
        index,
      ),
      identity: this.canvasService.getStudentResultPageIdentity(this.accessToken, index),
      version: this.canvasService.getStudentResultPageVersion(this.accessToken, index),
      image: this.canvasService.getStudentResultPageImage(this.accessToken, index),
    }).subscribe({
      next: ({ annotations, identity, version, image }) => {
        this.revokeCurrentUrl();
        this.currentObjectUrl = URL.createObjectURL(image);
        this.imageUrl.set(this.currentObjectUrl);
        this.annotations.set(annotations);
        this.boxes.set(annotations.flatMap((annotation) => this.toBoxes(annotation)));
        this.regions.set(annotations.map((annotation) => this.toRegion(annotation)));
        this.identity.set(identity);
        this.version.set(version);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Unable to load this page of the exam. The link may have expired.');
        this.loading.set(false);
      },
    });
  }

  private failAccess(): void {
    this.accessToken = '';
    this.error.set('This Canvas result link is invalid or has expired.');
    this.loadingGrade.set(false);
    this.loading.set(false);
  }

  private toBoxes(annotation: QuestionAnnotation): PositionedBox[] {
    const selectedClass = annotation.ambiguous
      ? 'status-ambiguous'
      : annotation.correct
        ? 'status-correct'
        : 'status-incorrect';
    return annotation.boxes.map((box) => ({
      key: `${annotation.question_id}-${box.label}`,
      questionId: annotation.question_id,
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      statusClass: box.selected ? selectedClass : 'status-empty',
    }));
  }

  private toRegion(annotation: QuestionAnnotation): PositionedRegion {
    return {
      questionId: annotation.question_id,
      x: annotation.bounds.x,
      y: annotation.bounds.y,
      width: annotation.bounds.width,
      height: annotation.bounds.height,
    };
  }

  private revokeCurrentUrl(): void {
    if (!this.currentObjectUrl) return;
    URL.revokeObjectURL(this.currentObjectUrl);
    this.currentObjectUrl = null;
  }
}
