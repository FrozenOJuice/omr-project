export type ScanStatus = 'pending' | 'completed' | 'failed';

// Mirrors the Scan.failure_code values set by the backend's
// services/scan_processing.py when status is 'failed'.
export type ScanFailureCode =
  | 'template_not_configured'
  | 'page_count_mismatch'
  | 'low_scan_quality'
  | 'page_out_of_order'
  | 'omr_service_error';

export interface Scan {
  id: string;
  uploader_user_id: string;
  exam_id: string;
  exam_template_id: string | null;
  path: string;
  page_count: number | null;
  status: ScanStatus;
  omr_scan_id: string | null;
  failure_code: ScanFailureCode | null;
  failure_detail: string | null;
  batch_id?: string | null;
  batch_index?: number | null;
}

// Live OMR progress for a scan's in-flight batch upload job (GET /api/scans/{id}/job-status).
export interface ScanJobStatus {
  progress: number; // 0-1
  finished: boolean;
  success: boolean | null;
  notes: string;
}
