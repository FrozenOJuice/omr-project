import { ChangeDetectorRef, Component, OnInit, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Course } from '../../../../models/course.model';
import {
  RecommendedRetentionPolicy,
  RetentionPolicy,
  RetentionPolicyDraft,
} from '../../../../models/retention-policy.model';
import { CourseService } from '../../../../services/course.service';


type RetentionModalMode = 'loading' | 'configure' | 'confirm' | 'edit';


@Component({
  selector: 'app-retention-policy-modal',
  imports: [FormsModule],
  templateUrl: './retention-policy-modal.html',
  styleUrl: './retention-policy-modal.css',
})
export class RetentionPolicyModal implements OnInit {
  private courseService = inject(CourseService);
  private cdr = inject(ChangeDetectorRef);

  course = input.required<Course>();
  cancel = output<void>();
  archived = output<void>();

  mode: RetentionModalMode = 'loading';
  policy: RetentionPolicy | null = null;
  recommended: RecommendedRetentionPolicy | null = null;
  draft: RetentionPolicyDraft = {
    scanned_image_retention_months: 12,
    exam_record_retention_months: 12,
    retain_anonymized_analytics: true,
  };
  isWorking = false;
  error = '';
  requiresActiveOverride = false;

  ngOnInit(): void {
    this.loadPolicy();
  }

  get isEditing(): boolean {
    return this.mode === 'edit';
  }

  get maximumRetentionMonths(): number {
    return this.recommended?.maximum_retention_months ?? 72;
  }

  get draftIsValid(): boolean {
    return this.validMonths(this.draft.scanned_image_retention_months)
      && this.validMonths(this.draft.exam_record_retention_months);
  }

  loadPolicy(): void {
    this.mode = 'loading';
    this.error = '';
    this.courseService.getRetentionPolicy().subscribe({
      next: (status) => {
        this.recommended = status.recommended;
        this.policy = status.policy;
        if (status.configured && status.policy) {
          this.mode = 'confirm';
          this.copyPolicyToDraft(status.policy);
        } else {
          this.mode = 'configure';
          this.draft = {
            scanned_image_retention_months: status.recommended.scanned_image_retention_months,
            exam_record_retention_months: status.recommended.exam_record_retention_months,
            retain_anonymized_analytics: status.recommended.retain_anonymized_analytics,
          };
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.error = 'Unable to load your retention policy.';
        this.cdr.markForCheck();
      },
    });
  }

  changePolicy(): void {
    if (this.policy) this.copyPolicyToDraft(this.policy);
    this.error = '';
    this.mode = 'edit';
  }

  cancelPolicyForm(): void {
    if (this.isEditing) {
      this.error = '';
      this.mode = 'confirm';
      return;
    }
    this.cancel.emit();
  }

  savePolicy(): void {
    if (!this.draftIsValid || this.isWorking) return;
    const archiveAfterSave = this.mode === 'configure';
    this.isWorking = true;
    this.error = '';

    this.courseService.upsertRetentionPolicy(this.draft).subscribe({
      next: (policy) => {
        this.policy = policy;
        if (archiveAfterSave) {
          this.archiveCourse();
        } else {
          this.isWorking = false;
          this.mode = 'confirm';
          this.cdr.markForCheck();
        }
      },
      error: (error) => {
        this.isWorking = false;
        this.error = error?.error?.error?.message || 'Unable to save the retention policy.';
        this.cdr.markForCheck();
      },
    });
  }

  confirmArchive(): void {
    if (this.isWorking) return;
    this.isWorking = true;
    this.error = '';
    this.archiveCourse(this.requiresActiveOverride);
  }

  private archiveCourse(overrideActiveCourse = false): void {
    this.courseService.archiveCourse(this.course().id, true, overrideActiveCourse).subscribe({
      next: () => {
        this.isWorking = false;
        this.archived.emit();
        this.cdr.markForCheck();
      },
      error: (error) => {
        this.isWorking = false;
        const code = error?.error?.error?.code;
        if (code === 'retention_policy_required') {
          this.loadPolicy();
          return;
        }
        if (code === 'course_still_active') {
          this.requiresActiveOverride = true;
          this.mode = 'confirm';
          this.error = 'This course has unfinished exams or pending re-grade requests. Archiving now hides it from students. Select Archive Anyway to explicitly override.';
          this.cdr.markForCheck();
          return;
        }
        this.error = error?.error?.error?.message || 'Unable to archive this course.';
        this.cdr.markForCheck();
      },
    });
  }

  private copyPolicyToDraft(policy: RetentionPolicy): void {
    this.draft = {
      scanned_image_retention_months: policy.scanned_image_retention_months,
      exam_record_retention_months: policy.exam_record_retention_months,
      retain_anonymized_analytics: policy.retain_anonymized_analytics,
    };
  }

  private validMonths(months: number): boolean {
    return Number.isInteger(months) && months >= 12 && months <= this.maximumRetentionMonths;
  }
}
