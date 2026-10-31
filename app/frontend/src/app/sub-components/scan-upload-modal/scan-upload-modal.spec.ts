import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { of, Subject, throwError } from 'rxjs';
import { ScanUploadModal } from './scan-upload-modal';
import { ScanService } from '../../services/scan.service';
import { Exam } from '../../models/exam.model';
import { Scan } from '../../models/scan.model';
import { ExamStatus } from '../../enums/tags.enum';
import { ExamService } from '../../services/exam.service';

const mockExam: Exam = {
  id: 'exam-1',
  name: 'Midterm',
  description: null,
  start_time: '2026-06-01T09:00:00Z',
  end_time: '2026-06-01T11:00:00Z',
  role: 'instructor',
  course_id: 'course-1',
  exam_template_id: 'template-1',
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  released: false,
  status: ExamStatus.UnGraded,
  scanned: 0,
  total: 0,
  completedAt: '',
  regradeCount: 0,
  ambiguousCount: 0,
  hasAnswerKey: true,
  answerKeysComplete: true,
  templateRegistered: true,
  templateMissing: false,
  templateWarning: null,
  generatedPdfPath: null,
};

const mockScan: Scan = {
  id: 'scan-1',
  uploader_user_id: 'user-1',
  exam_id: 'exam-1',
  exam_template_id: 'template-1',
  path: 'scans/scan-1.pdf',
  page_count: 4,
  status: 'pending',
  omr_scan_id: null,
  failure_code: null,
  failure_detail: null,
};

const mockScanService = {
  uploadScan: vi.fn(() => of([mockScan])),
  listScansByExam: vi.fn(() => of([] as Scan[])),
  downloadScan: vi.fn(() => of(new Blob(['%PDF-1.4']))),
  deleteScan: vi.fn(() => of(void 0)),
  deleteAllScansForExam: vi.fn(() => of(void 0)),
};

const mockExamService = {
  listExamGrades: vi.fn(() => of([])),
};

describe('ScanUploadModal', () => {
  let component: ScanUploadModal;
  let fixture: ComponentFixture<ScanUploadModal>;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    mockScanService.listScansByExam.mockReturnValue(of([] as Scan[]));
    mockScanService.downloadScan.mockReturnValue(of(new Blob(['%PDF-1.4'])));
    mockScanService.deleteScan.mockReturnValue(of(void 0));
    mockScanService.deleteAllScansForExam.mockReturnValue(of(void 0));
    mockExamService.listExamGrades.mockReturnValue(of([]));
    await TestBed.configureTestingModule({
      imports: [ScanUploadModal],
      providers: [
        { provide: ScanService, useValue: mockScanService },
        { provide: ExamService, useValue: mockExamService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ScanUploadModal);
    component = fixture.componentInstance;
    component.exam = { ...mockExam };
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ngOnInit — existing scans

  it('should surface an exam\'s existing scans as already on file', () => {
    mockScanService.listScansByExam.mockReturnValue(of([{ ...mockScan, status: 'completed' }]));
    component.ngOnInit();
    expect(component.uploadedScans()).toEqual([{ ...mockScan, status: 'completed' }]);
    expect(component.uploadSuccess()).toBe(true);
    expect(component.justUploaded()).toBe(false);
  });

  it('should surface duplicate-student grade flags beside uploaded scans', () => {
    mockScanService.listScansByExam.mockReturnValue(
      of([{ ...mockScan, status: 'completed' }]),
    );
    mockExamService.listExamGrades.mockReturnValue(
      of([{ flag_reason: 'duplicate_student_grade' }] as any),
    );

    component.ngOnInit();
    fixture.detectChanges();

    expect(component.duplicateConflictCount).toBe(1);
    expect(fixture.nativeElement.querySelector('.duplicate-warning')?.textContent)
      .toContain('scan may duplicate');
  });

  it('should leave the upload form untouched when the exam has no scans yet', () => {
    mockScanService.listScansByExam.mockReturnValue(of([]));
    component.ngOnInit();
    expect(component.uploadSuccess()).toBe(false);
    expect(component.uploadedScans()).toEqual([]);
  });

  it('should keep polling an existing scan that is still pending', () => {
    mockScanService.listScansByExam.mockReturnValue(of([mockScan]));
    mockScanService.listScansByExam.mockClear();
    component.ngOnInit();
    // one call to fetch on init, one immediate re-check from pollScanStatuses's startWith(0)
    expect(mockScanService.listScansByExam).toHaveBeenCalledTimes(2);
  });

  // scanFileName

  it('should strip the storage path\'s random prefix from the displayed file name', () => {
    const scan = { ...mockScan, path: 'exams/exam-1/template-1/3f9a2b1c8e4d4f6a9c2b1e0d5f6a7b8c_midterm_batch.pdf' };
    expect(component.scanFileName(scan)).toBe('midterm_batch.pdf');
  });

  it('should fall back to the basename when the storage path has no prefix to strip', () => {
    const scan = { ...mockScan, path: 'scans/scan-1.pdf' };
    expect(component.scanFileName(scan)).toBe('scan-1.pdf');
  });

  // Initial state

  it('should initialise with no files selected', () => {
    expect(component.files()).toEqual([]);
  });

  it('should initialise as not uploading', () => {
    expect(component.isUploading()).toBe(false);
  });

  it('should initialise with zero progress', () => {
    expect(component.uploadProgress()).toBe(0);
  });

  it('should initialise with no error', () => {
    expect(component.uploadError()).toBe('');
  });

  it('should initialise without success state', () => {
    expect(component.uploadSuccess()).toBe(false);
  });

  it('should load existing scans on init', () => {
    expect(mockScanService.listScansByExam).toHaveBeenCalledWith('exam-1');
  });

  // onFileChange

  it('onFileChange should set files from event', () => {
    const file = new File(['%PDF-1.4'], 'scan.pdf', { type: 'application/pdf' });
    const event = { target: { files: [file] } } as unknown as Event;
    component.onFileChange(event);
    expect(component.files()).toEqual([file]);
  });

  it('onFileChange should clear uploadError', () => {
    component.uploadError.set('some error');
    const event = { target: { files: [new File([''], 'scan.pdf')] } } as unknown as Event;
    component.onFileChange(event);
    expect(component.uploadError()).toBe('');
  });

  it('onFileChange should clear uploadSuccess', () => {
    component.uploadSuccess.set(true);
    const event = { target: { files: [new File([''], 'scan.pdf')] } } as unknown as Event;
    component.onFileChange(event);
    expect(component.uploadSuccess()).toBe(false);
  });

  it('onFileChange should set files to an empty array when no files are selected', () => {
    const event = { target: { files: [] } } as unknown as Event;
    component.onFileChange(event);
    expect(component.files()).toEqual([]);
  });

  // clearFile

  it('clearFile should reset files', () => {
    component.files.set([new File([''], 'scan.pdf')]);
    component.clearFile();
    expect(component.files()).toEqual([]);
  });

  it('clearFile should reset uploadError', () => {
    component.uploadError.set('some error');
    component.clearFile();
    expect(component.uploadError()).toBe('');
  });

  it('clearFile should reset uploadSuccess', () => {
    component.uploadSuccess.set(true);
    component.clearFile();
    expect(component.uploadSuccess()).toBe(false);
  });

  it('clearFile should reset uploadProgress', () => {
    component.uploadProgress.set(60);
    component.clearFile();
    expect(component.uploadProgress()).toBe(0);
  });

  it('clearFile should reset uploadedScans', () => {
    component.uploadedScans.set([mockScan]);
    component.clearFile();
    expect(component.uploadedScans()).toEqual([]);
  });

  // upload guards

  it('upload should do nothing when no files are selected', () => {
    component.files.set([]);
    component.upload();
    expect(mockScanService.uploadScan).not.toHaveBeenCalled();
  });

  // upload — success

  it('upload should call uploadScan with the exam template id', () => {
    const file = new File([''], 'scan.pdf');
    component.files.set([file]);
    component.upload();
    expect(mockScanService.uploadScan).toHaveBeenCalledWith(
      'exam-1',
      'template-1',
      file,
      null,
      expect.any(Function),
    );
  });

  it('upload should show an error when the exam has no template id', () => {
    component.exam = { ...mockExam, exam_template_id: null };
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadError()).toBe('This exam has no bubble-sheet template attached.');
    expect(mockScanService.uploadScan).not.toHaveBeenCalled();
  });

  it('upload should set isUploading to true during upload', () => {
    const pending = new Subject<Scan[]>();
    mockScanService.uploadScan.mockReturnValueOnce(pending.asObservable());
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    // pending has not emitted yet, so isUploading should still be true
    expect(component.isUploading()).toBe(true);
    pending.next([mockScan]);
    pending.complete();
    expect(component.isUploading()).toBe(false);
  });

  it('upload should emit scanUploaded on success', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    const emitSpy = vi.spyOn(component.scanUploaded, 'emit');
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(emitSpy).toHaveBeenCalledWith([mockScan]);
  });

  it('upload should store uploadedScans on success', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadedScans()).toEqual([mockScan]);
  });

  it('upload should add uploaded scans to the scan list', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.allScans()).toEqual([mockScan]);
  });

  it('upload should refresh scan processing status', () => {
    const completedScan: Scan = { ...mockScan, status: 'completed', omr_scan_id: 'omr-scan-1' };
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    mockScanService.listScansByExam.mockReturnValue(of([completedScan]));

    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();

    expect(mockScanService.listScansByExam).toHaveBeenCalledWith('exam-1');
    expect(component.uploadedScans()).toEqual([completedScan]);
  });

  it('upload should track multiple scans from a batch upload', () => {
    const scanTwo: Scan = { ...mockScan, id: 'scan-2' };
    mockScanService.uploadScan.mockReturnValue(of([mockScan, scanTwo]));

    component.files.set([new File([''], 'batch.pdf')]);
    component.upload();

    expect(component.uploadedScans()).toEqual([mockScan, scanTwo]);
  });

  it('upload polling expands a batch placeholder into all OMR scan rows', () => {
    const placeholder: Scan = { ...mockScan, batch_id: 'batch-1', batch_index: 1 };
    const completed: Scan = {
      ...placeholder,
      status: 'completed',
      omr_scan_id: 'omr-1',
    };
    const child: Scan = {
      ...completed,
      id: 'scan-2',
      omr_scan_id: 'omr-2',
      batch_index: 2,
    };
    mockScanService.uploadScan.mockReturnValue(of([placeholder]));
    mockScanService.listScansByExam.mockReturnValue(of([completed, child]));

    component.files.set([new File([''], 'batch.pdf')]);
    component.upload();

    expect(component.uploadedScans()).toEqual([completed, child]);
    expect(component.processingMessage()).toBe('All 2 scans processed successfully.');
  });

  it('processingMessage should describe a single pending scan', () => {
    component.uploadedScans.set([mockScan]);
    expect(component.processingMessage()).toBe('Processing scan...');
  });

  it('processingMessage should describe multiple pending scans', () => {
    component.uploadedScans.set([mockScan, { ...mockScan, id: 'scan-2' }]);
    expect(component.processingMessage()).toBe('Processing 2 scans...');
  });

  it('processingMessage should describe a single completed scan', () => {
    component.uploadedScans.set([{ ...mockScan, status: 'completed' }]);
    expect(component.processingMessage()).toBe('Scan processed successfully.');
  });

  it('processingMessage should describe all scans completed', () => {
    component.uploadedScans.set([
      { ...mockScan, status: 'completed' },
      { ...mockScan, id: 'scan-2', status: 'completed' },
    ]);
    expect(component.processingMessage()).toBe('All 2 scans processed successfully.');
  });

  it('processingMessage should describe a single failed scan', () => {
    component.uploadedScans.set([{ ...mockScan, status: 'failed' }]);
    expect(component.processingMessage()).toBe('Scan processing failed.');
  });

  it('processingMessage falls back to a generic message when the failed scan has no failure_code', () => {
    component.uploadedScans.set([{ ...mockScan, status: 'failed', failure_code: null }]);
    expect(component.processingMessage()).toBe('Scan processing failed.');
  });

  it('processingMessage surfaces the failure_code-specific message when present', () => {
    component.uploadedScans.set([{ ...mockScan, status: 'failed', failure_code: 'low_scan_quality' }]);
    expect(component.processingMessage()).toBe(
      'The scan is too skewed, faint, or low-resolution to read reliably. Try rescanning at a higher quality.',
    );
  });

  it('processingMessage surfaces the page_out_of_order message when present', () => {
    component.uploadedScans.set([{ ...mockScan, status: 'failed', failure_code: 'page_out_of_order' }]);
    expect(component.processingMessage()).toBe(
      'One or more pages appear to be out of order (e.g. the back page was scanned before the front). Check the page order and try again.',
    );
  });

  it('deleteScan should remove a failed scan and request a refresh', () => {
    const failedScan: Scan = { ...mockScan, status: 'failed' };
    const refreshSpy = vi.spyOn(component.refreshRequested, 'emit');
    component.allScans.set([failedScan]);
    component.uploadedScans.set([failedScan]);

    component.deleteScan(failedScan);

    expect(mockScanService.deleteScan).toHaveBeenCalledWith('scan-1');
    expect(component.allScans()).toEqual([]);
    expect(component.uploadedScans()).toEqual([]);
    expect(refreshSpy).toHaveBeenCalled();
  });

  it('deleteScan should remove a completed scan (e.g. stuck without an answer key)', () => {
    const completedScan: Scan = { ...mockScan, status: 'completed' };
    const refreshSpy = vi.spyOn(component.refreshRequested, 'emit');
    component.allScans.set([completedScan]);
    component.uploadedScans.set([completedScan]);

    component.deleteScan(completedScan);

    expect(mockScanService.deleteScan).toHaveBeenCalledWith('scan-1');
    expect(component.allScans()).toEqual([]);
    expect(component.uploadedScans()).toEqual([]);
    expect(refreshSpy).toHaveBeenCalled();
  });

  // Delete all

  it('confirmDeleteAll does nothing when there are no scans to delete', () => {
    component.allScans.set([]);
    component.confirmDeleteAll();
    expect(component.confirmingDeleteAll()).toBe(false);
  });

  it('confirmDeleteAll opens the confirmation once scans exist', () => {
    component.allScans.set([mockScan]);
    component.confirmDeleteAll();
    expect(component.confirmingDeleteAll()).toBe(true);
  });

  it('cancelDeleteAll closes the confirmation without deleting anything', () => {
    component.allScans.set([mockScan]);
    component.confirmDeleteAll();

    component.cancelDeleteAll();

    expect(component.confirmingDeleteAll()).toBe(false);
    expect(mockScanService.deleteAllScansForExam).not.toHaveBeenCalled();
  });

  it('executeDeleteAll deletes every scan for the exam and clears local state', () => {
    const refreshSpy = vi.spyOn(component.refreshRequested, 'emit');
    component.allScans.set([mockScan, { ...mockScan, id: 'scan-2' }]);
    component.uploadedScans.set([mockScan, { ...mockScan, id: 'scan-2' }]);
    component.duplicateConflictCount = 2;
    component.confirmDeleteAll();

    component.executeDeleteAll();

    expect(mockScanService.deleteAllScansForExam).toHaveBeenCalledWith('exam-1');
    expect(component.allScans()).toEqual([]);
    expect(component.uploadedScans()).toEqual([]);
    expect(component.duplicateConflictCount).toBe(0);
    expect(component.isDeletingAll()).toBe(false);
    expect(component.confirmingDeleteAll()).toBe(false);
    expect(refreshSpy).toHaveBeenCalled();
  });

  it('executeDeleteAll sets isDeletingAll while the request is in flight', () => {
    const pending = new Subject<undefined>();
    mockScanService.deleteAllScansForExam.mockReturnValueOnce(pending.asObservable());
    component.allScans.set([mockScan]);
    component.confirmDeleteAll();

    component.executeDeleteAll();

    expect(component.isDeletingAll()).toBe(true);
    pending.next(undefined);
    pending.complete();
    expect(component.isDeletingAll()).toBe(false);
  });

  it('executeDeleteAll surfaces an error and keeps the scan list untouched on failure', () => {
    mockScanService.deleteAllScansForExam.mockReturnValueOnce(throwError(() => new Error()));
    component.allScans.set([mockScan]);
    component.confirmDeleteAll();

    component.executeDeleteAll();

    expect(component.scanListError()).toBe('Unable to delete all scans.');
    expect(component.allScans()).toEqual([mockScan]);
    expect(component.isDeletingAll()).toBe(false);
    expect(component.confirmingDeleteAll()).toBe(false);
  });


  it('upload should set uploadSuccess to true on success', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadSuccess()).toBe(true);
  });

  it('upload should set uploadProgress to 100 on success', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadProgress()).toBe(100);
  });

  it('upload should reset isUploading on success', () => {
    mockScanService.uploadScan.mockReturnValue(of([mockScan]));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.isUploading()).toBe(false);
  });

  // upload — failure

  it('upload should set uploadError on failure', () => {
    mockScanService.uploadScan.mockReturnValue(throwError(() => new Error()));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadError()).toBeTruthy();
  });

  it('upload should show backend detail on failure', () => {
    mockScanService.uploadScan.mockReturnValue(
      throwError(() => ({
        error: { error: { message: 'PDF has 1 page(s); expected a multiple of 2 page(s) per exam' } },
      })),
    );
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadError()).toBe('PDF has 1 page(s); expected a multiple of 2 page(s) per exam');
  });

  it('upload should join Pydantic validation-error messages on a 422 failure', () => {
    mockScanService.uploadScan.mockReturnValue(
      throwError(() => ({
        error: { error: { message: 'Invalid request', details: [{ msg: 'file must be a PDF' }] } },
      })),
    );
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadError()).toBe('file must be a PDF');
  });

  it('upload should reset isUploading on failure', () => {
    mockScanService.uploadScan.mockReturnValue(throwError(() => new Error()));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.isUploading()).toBe(false);
  });

  it('upload should reset uploadProgress to 0 on failure', () => {
    mockScanService.uploadScan.mockReturnValue(throwError(() => new Error()));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadProgress()).toBe(0);
  });

  it('upload should not set uploadSuccess on failure', () => {
    mockScanService.uploadScan.mockReturnValue(throwError(() => new Error()));
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    expect(component.uploadSuccess()).toBe(false);
  });

  // progress callback

  it('upload should update uploadProgress via onProgress callback', () => {
    let capturedCallback: ((pct: number) => void) | undefined;

    (mockScanService.uploadScan as any).mockImplementation((_e: any, _t: any, _f: any, _p: any, onProgress: any) => {
      capturedCallback = onProgress;
      return of([mockScan]);
    });
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    capturedCallback?.(50);
    expect(component.uploadProgress()).toBe(50);
  });

  // wizardStep (embedded as step 3 of the exam-creation wizard)

  it('does not show the step indicator or Back button outside the wizard', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-wizard-steps')).toBeNull();
    expect(fixture.nativeElement.querySelector('[title="Back to answer key"]')).toBeNull();
  });

  it('shows the step indicator and a Back button once wizardStep is set', () => {
    fixture.componentRef.setInput('wizardStep', 3);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-wizard-steps')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[title="Back to answer key"]')).not.toBeNull();
  });

  it('emits backRequested when the Back button is clicked before a file is uploaded', () => {
    fixture.componentRef.setInput('wizardStep', 3);
    fixture.detectChanges();
    const spy = vi.fn();
    component.backRequested.subscribe(spy);

    fixture.nativeElement.querySelector('[title="Back to answer key"]').click();

    expect(spy).toHaveBeenCalled();
  });

  it('still shows the Back button in the wizard after a successful upload', () => {
    fixture.componentRef.setInput('wizardStep', 3);
    component.files.set([new File([''], 'scan.pdf')]);
    component.upload();
    fixture.detectChanges();

    const spy = vi.fn();
    component.backRequested.subscribe(spy);
    const backBtn = fixture.nativeElement.querySelector('[title="Back to answer key"]');
    expect(backBtn).not.toBeNull();

    backBtn.click();
    expect(spy).toHaveBeenCalled();
  });

  // Delete-all template wiring

  it('disables the Delete All button when there are no scans', () => {
    // The scan-list section (and therefore this button) only renders once
    // there's a scan or a list-load error to show -- exercise the latter so
    // allScans() can be empty while the button is still on the page.
    component.allScans.set([]);
    component.scanListError.set('Unable to load previous scans.');
    fixture.detectChanges();

    const deleteAllBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.action-btn--danger');
    expect(deleteAllBtn.disabled).toBe(true);
  });

  it('clicking Delete All opens a confirmation dialog instead of deleting immediately', () => {
    mockScanService.listScansByExam.mockReturnValue(of([mockScan]));
    component.ngOnInit();
    fixture.detectChanges();

    fixture.nativeElement.querySelector('.action-btn--danger').click();
    fixture.detectChanges();

    expect(mockScanService.deleteAllScansForExam).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('.confirm-card')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.confirm-title').textContent).toContain('Delete All Scans?');
  });

  it('confirming the dialog calls deleteAllScansForExam and closes it', () => {
    mockScanService.listScansByExam.mockReturnValue(of([mockScan]));
    component.ngOnInit();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.action-btn--danger').click();
    fixture.detectChanges();

    const confirmBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.confirm-actions .action-btn--danger');
    confirmBtn.click();
    fixture.detectChanges();

    expect(mockScanService.deleteAllScansForExam).toHaveBeenCalledWith('exam-1');
    expect(fixture.nativeElement.querySelector('.confirm-card')).toBeNull();
  });

  it('cancelling the dialog leaves the scans untouched', () => {
    mockScanService.listScansByExam.mockReturnValue(of([mockScan]));
    component.ngOnInit();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.action-btn--danger').click();
    fixture.detectChanges();

    fixture.nativeElement.querySelector('.confirm-actions .action-btn--outline').click();
    fixture.detectChanges();

    expect(mockScanService.deleteAllScansForExam).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('.confirm-card')).toBeNull();
  });

});
