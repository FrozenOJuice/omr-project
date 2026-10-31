export type UserRole = 'Admin' | 'Professor' | 'Student';
export type ApiUserRole = 'student' | 'professor' | 'admin';
export type ApiAccountStatus = 'active' | 'disabled';

export interface ApiAdminUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  role: ApiUserRole;
  status: ApiAccountStatus;
  student_number: string | null;
  created_at: string;
  active_session: boolean;
}

export interface AdminUserListResponse {
  items: ApiAdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminSummary {
  total_users: number;
  active_users: number;
  disabled_users: number;
  admins: number;
  professors: number;
  students: number;
  active_sessions: number;
}

export interface CreateAdminUserRequest {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  role: ApiUserRole;
  status: ApiAccountStatus;
  student_number?: string | null;
}

export interface UpdateAdminUserRequest {
  first_name?: string;
  last_name?: string;
  email?: string;
  student_number?: string | null;
}

export interface ListAdminUsersParams {
  search?: string;
  role?: ApiUserRole;
  status?: ApiAccountStatus;
  limit?: number;
  offset?: number;
}

export class AdminUser {
  constructor(
    public id: string,
    public firstName: string,
    public lastName: string,
    public email: string,
    public role: UserRole,
    public status: ApiAccountStatus,
    public createdAt: string,
    public activeSession: boolean,
    public studentNumber: string | null = null,
  ) {}

  get fullName(): string {
    return `${this.firstName} ${this.lastName}`.trim();
  }
}

export class ActiveSession {
  constructor(
    public userId: string,
    public name: string,
    public email: string,
    public loginTime: string,
  ) {}
}

export function apiRoleToUserRole(role: ApiUserRole): UserRole {
  switch (role) {
    case 'admin':
      return 'Admin';
    case 'professor':
      return 'Professor';
    case 'student':
      return 'Student';
  }
}

export function userRoleToApiRole(role: UserRole): ApiUserRole {
  switch (role) {
    case 'Admin':
      return 'admin';
    case 'Professor':
      return 'professor';
    case 'Student':
      return 'student';
  }
}

export function apiAdminUserToAdminUser(user: ApiAdminUser): AdminUser {
  return new AdminUser(
    user.id,
    user.first_name,
    user.last_name,
    user.email,
    apiRoleToUserRole(user.role),
    user.status,
    user.created_at,
    user.active_session,
    user.student_number,
  );
}
