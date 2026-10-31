import { InstitutionCode } from './institution.model';

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  status: string;
  student_number: string | null;
  password_changed_at: string;
  email_notifications_enabled: boolean;
  regrade_alerts_enabled: boolean;
  batch_job_complete_enabled: boolean;
  institution: InstitutionCode;
}

export interface NotificationPreferences {
  email_notifications_enabled: boolean;
  regrade_alerts_enabled: boolean;
  batch_job_complete_enabled: boolean;
}
