import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { vi } from 'vitest';

import { Scan } from '../models/scan.model';
import { ScanService } from './scan.service';


describe('ScanService batch PDF upload', () => {
  let service: ScanService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ScanService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.unstubAllGlobals();
  });

  it('uses the backend PDF batch route for small files', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: (name: string) => name === 'ETag' ? 'etag-1' : null },
    }));
    const file = new File(['small pdf'], 'batch.pdf', { type: 'application/pdf' });
    const resultPromise = firstValueFrom(
      service.uploadScan('exam-1', 'template-1', file, null),
    );

    const upload = http.expectOne('/api/scans/pdf');
    expect(upload.request.body.get('file')).toBe(file);
    const placeholder = {
      id: 'scan-1',
      uploader_user_id: 'user-1',
      exam_id: 'exam-1',
      exam_template_id: 'template-1',
      path: 'exams/exam-1/template-1/batch.pdf',
      page_count: 2,
      status: 'pending',
      omr_scan_id: null,
      failure_code: null,
      failure_detail: null,
      batch_id: 'batch-1',
      batch_index: 1,
    } satisfies Scan;
    upload.flush([placeholder]);

    await expect(resultPromise).resolves.toEqual([placeholder]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('keeps the existing direct-to-storage upload for large files', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'etag-1' },
    }));
    // Real content is tiny; the size is overridden below so the service's
    // >200MB simple-upload threshold check sees a "large" file without
    // actually allocating 200MB in the test.
    const file = new File(['large pdf'], 'large.pdf');
    Object.defineProperty(file, 'size', { value: 200_000_001 });
    const totalChunks = Math.ceil(200_000_001 / (5 * 1024 * 1024));
    const resultPromise = firstValueFrom(
      service.uploadScan('exam-1', 'template-1', file, null),
    );

    const initiate = http.expectOne('/api/scans/initiate');
    expect(initiate.request.body.total_chunks).toBe(totalChunks);
    initiate.flush({
      upload_id: 'upload-1',
      storage_path: 'exams/exam-1/template-1/large.pdf',
      urls: Array.from({ length: totalChunks }, (_, i) => ({
        part_number: i + 1,
        url: `http://garage/part-${i + 1}`,
      })),
    });

    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(totalChunks));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const finalize = http.expectOne('/api/scans/finalize-pdf');
    finalize.flush([]);

    await expect(resultPromise).resolves.toEqual([]);
  });
});
