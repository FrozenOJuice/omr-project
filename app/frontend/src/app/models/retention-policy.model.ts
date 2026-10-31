export interface RetentionPolicy {
  id: string;
  owner_user_id: string;
  scanned_image_retention_months: number;
  exam_record_retention_months: number;
  retain_anonymized_analytics: boolean;
  source: 'ubc_default' | 'custom';
  created_at: string;
  updated_at: string;
}

export interface RetentionPolicyDraft {
  scanned_image_retention_months: number;
  exam_record_retention_months: number;
  retain_anonymized_analytics: boolean;
}

export interface RecommendedRetentionPolicy extends RetentionPolicyDraft {
  maximum_retention_months: number;
  basis: string;
  source_urls: string[];
}

export interface RetentionPolicyStatus {
  configured: boolean;
  policy: RetentionPolicy | null;
  recommended: RecommendedRetentionPolicy;
}
