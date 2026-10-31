import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnDestroy, OnInit, Output, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription, catchError, concatMap, from, interval, of, startWith, switchMap, takeWhile, tap, toArray } from 'rxjs';
import { Exam } from '../../models/exam.model';
import { Scan, ScanFailureCode } from '../../models/scan.model';
import { ScanService } from '../../services/scan.service';
import { ExamService } from '../../services/exam.service';
import { WizardSteps } from '../wizard-steps/wizard-steps';

// User-facing messages for each Scan.failure_code, so staff know whether to
// reach for a rescan, a different file, or the exam template setup instead of
// a bare "processing failed".
const FAILURE_MESSAGES: Record<ScanFailureCode, string> = {
  template_not_configured: "This exam's template isn't fully set up yet. Contact an admin before uploading scans.",
  page_count_mismatch: "This file doesn't have the number of pages expected for this exam. Check you uploaded the right file.",
  low_scan_quality: 'The scan is too skewed, faint, or low-resolution to read reliably. Try rescanning at a higher quality.',
  page_out_of_order: 'One or more pages appear to be out of order (e.g. the back page was scanned before the front). Check the page order and try again.',
  omr_service_error: 'The scanning service had trouble processing this file. Please try uploading again.',
};

@Component({
  selector: 'app-scan-upload-modal',
  imports: [FormsModule, WizardSteps],
  templateUrl: './scan-upload-modal.html',
  styleUrl: './scan-upload-modal.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanUploadModal implements OnInit, OnDestroy {
  private scanService = inject(ScanService);
  private examService = inject(ExamService);
  private statusSub?: Subscription;

  @Input() exam!: Exam;
  // When set, this is the last step of the exam-creation wizard (course-detail.html):
  // shows the step indicator and a back button to return to the answer-key step.
  @Input() wizardStep: number | null = null;
  @Output() close = new EventEmitter<void>();
  @Output() scanUploaded = new EventEmitter<Scan[]>();
  @Output() refreshRequested = new EventEmitter<void>();
  @Output() backRequested = new EventEmitter<void>();

  readonly files = signal<File[]>([]);
  readonly isUploading = signal(false);
  readonly uploadProgress = signal(0);
  readonly uploadError = signal('');
  readonly uploadSuccess = signal(false);
  readonly uploadedScans = signal<Scan[]>([]);
  readonly allScans = signal<Scan[]>([]);
  readonly scanListError = signal('');
  readonly deletingScanId = signal<string | null>(null);
  readonly confirmingDeleteAll = signal(false);
  readonly isDeletingAll = signal(false);
  readonly justUploaded = signal(false);
  duplicateConflictCount = 0;

  ngOnInit(): void {
    this.scanService.listScansByExam(this.exam.id).subscribe({
      next: (scans) => {
        this.allScans.set(this.sortScans(scans));
        if (scans.length === 0) return;
        this.uploadedScans.set(scans);
        this.uploadSuccess.set(true);
        this.refreshDuplicateConflicts();
        if (scans.some((scan) => scan.status === 'pending')) {
          this.pollScanStatuses();
        }
      },
    });
  }

  ngOnDestroy(): void {
    this.statusSub?.unsubscribe();
  }

  readonly processingMessage = computed(() => {
    const uploadedScans = this.uploadedScans();
    const total = uploadedScans.length;
    if (total === 0) {
      return '';
    }

    const pending = uploadedScans.filter((scan) => scan.status === 'pending').length;
    if (pending > 0) {
      return total === 1 ? 'Processing scan...' : `Processing ${total} scans...`;
    }

    const failedScans = uploadedScans.filter((scan) => scan.status === 'failed');
    if (failedScans.length === 0) {
      return total === 1 ? 'Scan processed successfully.' : `All ${total} scans processed successfully.`;
    }

    // With more than one failure, showing a single specific reason would be
    // misleading — different scans can fail for different reasons — so fall
    // back to a count. With exactly one, surface its specific reason (or a
    // generic fallback) even if other scans in the batch succeeded.
    if (failedScans.length > 1) {
      return `${failedScans.length} of ${total} scans failed to process.`;
    }

    const code = failedScans[0].failure_code;
    return (code && FAILURE_MESSAGES[code]) || 'Scan processing failed.';
  });

  readonly processingIcon = computed(() => {
    const uploadedScans = this.uploadedScans();
    if (uploadedScans.some((scan) => scan.status === 'pending')) {
      return 'sync';
    }

    if (uploadedScans.some((scan) => scan.status === 'failed')) {
      return 'error';
    }

    return uploadedScans.length > 0 ? 'check_circle' : 'sync';
  });

  readonly anyFailed = computed(() => this.uploadedScans().some((scan) => scan.status === 'failed'));

  readonly allCompleted = computed(() =>
    this.uploadedScans().length > 0 && this.uploadedScans().every((scan) => scan.status === 'completed'),
  );

  readonly totalFileSize = computed(() => this.files().reduce((sum, file) => sum + file.size, 0));

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.files.set(input.files ? Array.from(input.files) : []);
    this.uploadError.set('');
    this.uploadSuccess.set(false);
  }

  clearFile(): void {
    this.files.set([]);
    this.uploadError.set('');
    this.uploadSuccess.set(false);
    this.uploadProgress.set(0);
    this.uploadedScans.set([]);
    this.justUploaded.set(false);
    this.statusSub?.unsubscribe();
  }

  upload(): void {
    const files = this.files();
    if (files.length === 0) return;
    if (!this.exam.exam_template_id) {
      this.uploadError.set('This exam has no bubble-sheet template attached.');
      return;
    }
    const examTemplateId = this.exam.exam_template_id;

    this.isUploading.set(true);
    this.uploadError.set('');
    this.uploadProgress.set(0);

    const total = files.length;
    const failures: Array<{ fileName: string; message: string }> = [];
    let uploadedCount = 0;

    from(files)
      .pipe(
        concatMap((file, index) =>
          this.scanService
            .uploadScan(this.exam.id, examTemplateId, file, null, (pct) => {
              this.uploadProgress.set(Math.round(((index + pct / 100) / total) * 100));
            })
            .pipe(
              tap((scans) => {
                uploadedCount++;
                this.uploadedScans.update((prev) => [...prev, ...scans]);
                this.mergeScans(scans);
                this.scanUploaded.emit(scans);
              }),
              catchError((err) => {
                failures.push({
                  fileName: file.name,
                  message: this.uploadErrorMessage(err),
                });
                return of(null);
              }),
            ),
        ),
        toArray(),
      )
      .subscribe(() => {
        this.isUploading.set(false);
        this.uploadProgress.set(uploadedCount > 0 ? 100 : 0);
        this.justUploaded.set(uploadedCount > 0);

        if (uploadedCount > 0) {
          this.uploadSuccess.set(true);
          this.pollScanStatuses();
        }
        if (failures.length === 1 && total === 1) {
          this.uploadError.set(failures[0].message);
        } else if (failures.length > 0) {
          const details = failures
            .map(({ fileName, message }) => `${fileName}: ${message}`)
            .join('; ');
          this.uploadError.set(uploadedCount === 0
            ? `All uploads failed: ${details}`
            : `Some files failed to upload: ${details}`);
        }
      });
  }

  private uploadErrorMessage(err: unknown): string {
    if (err instanceof Error && err.message) {
      return err.message;
    }
    // Backend error responses are wrapped as {"error": {"message","details",...}}
    // (see app/backend/errors/handler.py's _error_response) -- "details" is
    // the Pydantic validation-error array on a 422, "message" is a plain
    // string on any other AppError-raised 4xx.
    const apiError = (err as { error?: { error?: { message?: unknown; details?: unknown } } })
      ?.error?.error;
    const details = apiError?.details;
    if (Array.isArray(details) && details.length > 0) {
      const joined = details
        .map((item) => {
          if (typeof item === 'string') return item;
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg);
          }
          return null;
        })
        .filter((message): message is string => !!message)
        .join(' ');
      if (joined) return joined;
    }
    if (typeof apiError?.message === 'string' && apiError.message.trim()) {
      return apiError.message;
    }
    return 'Upload failed. Please try again.';
  }

  loadScans(): void {
    this.scanListError.set('');
    this.scanService.listScansByExam(this.exam.id).subscribe({
      next: (scans) => {
        this.allScans.set(this.sortScans(scans));
        this.refreshDuplicateConflicts();
      },
      error: () => {
        this.scanListError.set('Unable to load previous scans.');
      },
    });
  }

  downloadScan(scan: Scan): void {
    this.scanService.downloadScan(scan.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = this.scanFileName(scan);
        link.click();
        URL.revokeObjectURL(url);
      },
      error: () => {
        this.scanListError.set('Unable to download this scan.');
      },
    });
  }

  deleteScan(scan: Scan): void {
    this.deletingScanId.set(scan.id);
    this.scanService.deleteScan(scan.id).subscribe({
      next: () => {
        this.deletingScanId.set(null);
        this.allScans.update((scans) => scans.filter((item) => item.id !== scan.id));
        this.uploadedScans.update((scans) => scans.filter((item) => item.id !== scan.id));
        this.refreshRequested.emit();
        this.refreshDuplicateConflicts();
      },
      error: () => {
        this.deletingScanId.set(null);
        this.scanListError.set('Unable to delete this scan.');
      },
    });
  }

  confirmDeleteAll(): void {
    if (this.allScans().length === 0) return;
    this.confirmingDeleteAll.set(true);
  }

  cancelDeleteAll(): void {
    this.confirmingDeleteAll.set(false);
  }

  executeDeleteAll(): void {
    this.isDeletingAll.set(true);
    this.scanListError.set('');
    this.scanService.deleteAllScansForExam(this.exam.id).subscribe({
      next: () => {
        this.isDeletingAll.set(false);
        this.confirmingDeleteAll.set(false);
        this.statusSub?.unsubscribe();
        this.allScans.set([]);
        this.uploadedScans.set([]);
        this.duplicateConflictCount = 0;
        this.refreshRequested.emit();
      },
      error: () => {
        this.isDeletingAll.set(false);
        this.confirmingDeleteAll.set(false);
        this.scanListError.set('Unable to delete all scans.');
      },
    });
  }

  scanStatusLabel(scan: Scan): string {
    if (scan.status === 'pending') return 'Processing';
    if (scan.status === 'completed') return 'Processed';
    return 'Failed';
  }

  scanFileName(scan: Scan): string {
    const basename = scan.path.split('/').pop() || 'scan.pdf';
    const underscoreIdx = basename.indexOf('_');
    return underscoreIdx >= 0 ? basename.slice(underscoreIdx + 1) : basename;
  }

  private pollScanStatuses(): void {
    this.statusSub?.unsubscribe();
    this.statusSub = interval(2500).pipe(
      startWith(0),
      switchMap(() => this.scanService.listScansByExam(this.exam.id)),
      takeWhile((scans) => {
        const uploadedScans = this.uploadedScans();
        const wasPending = uploadedScans.some((scan) => scan.status === 'pending');
        const activeBatchIds = new Set(
          uploadedScans
            .map((scan) => scan.batch_id)
            .filter((batchId): batchId is string => !!batchId),
        );
        const currentBatchScans = activeBatchIds.size > 0
          ? scans.filter((scan) => !!scan.batch_id && activeBatchIds.has(scan.batch_id))
          : uploadedScans.map((prev) => scans.find((scan) => scan.id === prev.id) ?? prev);
        this.uploadedScans.set(this.sortScans(currentBatchScans));
        this.mergeScans(scans);

        const stillPending = this.uploadedScans().some((scan) => scan.status === 'pending');
        // Refresh once the batch has fully resolved, regardless of outcome --
        // a batch that entirely fails still needs the exam's stats/status to
        // catch up, not just a batch with at least one success.
        if (wasPending && !stillPending) {
          this.refreshRequested.emit();
          this.refreshDuplicateConflicts();
        }
        return stillPending;
      }, true),
    ).subscribe({
      error: () => {
        this.uploadError.set('Upload succeeded, but scan status could not be refreshed.');
      },
    });
  }

  private mergeScans(scans: Scan[]): void {
    const byId = new Map(this.allScans().map((scan) => [scan.id, scan]));
    scans.forEach((scan) => byId.set(scan.id, scan));
    this.allScans.set(this.sortScans([...byId.values()]));
  }

  private refreshDuplicateConflicts(): void {
    this.examService.listExamGrades(this.exam.id).subscribe({
      next: (grades) => {
        this.duplicateConflictCount = grades.filter((grade) =>
          (grade.flag_reason ?? '')
            .split(',')
            .map((reason) => reason.trim())
            .includes('duplicate_student_grade'),
        ).length;
      },
      // Scan upload remains usable if the grade summary cannot be refreshed.
      error: () => {},
    });
  }

  private sortScans(scans: Scan[]): Scan[] {
    return [...scans].sort((a, b) => {
      const batchA = a.batch_index ?? Number.MAX_SAFE_INTEGER;
      const batchB = b.batch_index ?? Number.MAX_SAFE_INTEGER;
      if (batchA !== batchB) return batchA - batchB;
      return a.path.localeCompare(b.path);
    });
  }
}
