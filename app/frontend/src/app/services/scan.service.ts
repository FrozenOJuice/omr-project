import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, switchMap, throwError } from 'rxjs';
import { Scan, ScanJobStatus } from '../models/scan.model';

const SIMPLE_UPLOAD_MAX = 200_000_000; // 200MB — matches backend limit
const CHUNK_SIZE = 5 * 1024 * 1024;   // 5MB per chunk
const MAX_PDF_SIZE = 195 * 1024 * 1024; // leaves room under OMR's 200MB request cap
const CHUNK_UPLOAD_CONCURRENCY = 4;   // parallel chunk PUTs in flight at once

interface InitiateResponse {
  upload_id: string;
  storage_path: string;
  urls: Array<{ part_number: number; url: string }>;
}

@Injectable({ providedIn: 'root' })
export class ScanService {
  private http = inject(HttpClient);

  uploadScan(
    examId: string,
    examTemplateId: string,
    file: File,
    pageCount: number | null,
    onProgress?: (pct: number) => void,
  ): Observable<Scan[]> {
    if (file.size > MAX_PDF_SIZE) {
      return throwError(() => new Error('PDF exceeds the 195MB processing limit.'));
    }
    if (file.size <= SIMPLE_UPLOAD_MAX) {
      return this.simpleUpload(examId, examTemplateId, file, pageCount);
    }
    return this.chunkedUpload(examId, examTemplateId, file, pageCount, onProgress);
  }

  listScansByExam(examId: string): Observable<Scan[]> {
    return this.http.get<Scan[]>(`/api/scans/exam/${examId}`);
  }

  getJobStatus(scanId: string): Observable<ScanJobStatus> {
    return this.http.get<ScanJobStatus>(`/api/scans/${scanId}/job-status`);
  }

  deleteScan(scanId: string): Observable<void> {
    return this.http.delete<void>(`/api/scans/${scanId}`);
  }

  deleteAllScansForExam(examId: string): Observable<void> {
    return this.http.delete<void>(`/api/scans/exam/${examId}`);
  }

  downloadScan(scanId: string): Observable<Blob> {
    return this.http.get(`/api/scans/${scanId}/download`, { responseType: 'blob' });
  }

  private simpleUpload(
    examId: string,
    examTemplateId: string,
    file: File,
    pageCount: number | null,
  ): Observable<Scan[]> {
    const formData = new FormData();
    formData.append('exam_id', examId);
    formData.append('exam_template_id', examTemplateId);
    formData.append('file', file);
    if (pageCount !== null) {
      formData.append('page_count', String(pageCount));
    }
    return this.http.post<Scan[]>('/api/scans/pdf', formData);
  }

  private chunkedUpload(
    examId: string,
    examTemplateId: string,
    file: File,
    pageCount: number | null,
    onProgress?: (pct: number) => void,
  ): Observable<Scan[]> {
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

    // Step 1: tell the backend how many chunks to expect. It creates a multipart
    // upload session in object storage and returns one pre-signed PUT URL per chunk.
    return this.http
      .post<InitiateResponse>('/api/scans/initiate', {
        exam_id: examId,
        exam_template_id: examTemplateId,
        filename: file.name,
        total_chunks: totalChunks,
        page_count: pageCount,
      })
      .pipe(
        // Step 2: upload each chunk directly to its pre-signed URL.
        // fetch is used instead of HttpClient because HttpClient would attach the
        // JWT auth header, which invalidates the pre-signed URL signature.
        // The storage server returns an ETag per chunk as a receipt.
        switchMap(async (init) => {
          const parts: Array<{ PartNumber: number; ETag: string }> = new Array(totalChunks);
          let completed = 0;
          let nextIndex = 0;

          const uploadChunk = async (i: number) => {
            const start = i * CHUNK_SIZE;
            const chunk = file.slice(start, Math.min(start + CHUNK_SIZE, file.size));
            const { url, part_number } = init.urls[i];

            const res = await fetch(url, { method: 'PUT', body: chunk });
            if (!res.ok) {
              throw new Error(`Chunk ${part_number} upload failed with status ${res.status}`);
            }
            const etag = res.headers.get('ETag');
            if (!etag) {
              throw new Error(`Chunk ${part_number} upload succeeded but returned no ETag`);
            }
            parts[i] = { PartNumber: part_number, ETag: etag };
            completed++;
            onProgress?.(Math.round((completed / totalChunks) * 100));
          };

          // Bounded worker pool: keeps a handful of chunk PUTs in flight at once
          // instead of awaiting each one before starting the next.
          const worker = async () => {
            while (nextIndex < totalChunks) {
              const i = nextIndex++;
              await uploadChunk(i);
            }
          };
          const workerCount = Math.min(CHUNK_UPLOAD_CONCURRENCY, totalChunks);
          await Promise.all(Array.from({ length: workerCount }, () => worker()));

          return { init, parts };
        }),
        // Step 3: send the ETags to the backend so it can instruct storage to
        // assemble the chunks into a single object, then persist the scan record.
        switchMap(({ init, parts }) =>
          this.http.post<Scan[]>('/api/scans/finalize-pdf', {
            upload_id: init.upload_id,
            storage_path: init.storage_path,
            exam_id: examId,
            exam_template_id: examTemplateId,
            parts,
            page_count: pageCount,
          }),
        ),
      );
  }
}
