import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AdminSummary,
  AdminUserListResponse,
  ApiAccountStatus,
  ApiAdminUser,
  ApiUserRole,
  CreateAdminUserRequest,
  ListAdminUsersParams,
  UpdateAdminUserRequest,
} from '../models/admin.model';

@Injectable({ providedIn: 'root' })
export class AdminService {
  private http = inject(HttpClient);

  getSummary(): Observable<AdminSummary> {
    return this.http.get<AdminSummary>('/api/admin/summary');
  }

  listUsers(params: ListAdminUsersParams = {}): Observable<AdminUserListResponse> {
    return this.http.get<AdminUserListResponse>('/api/admin/users', {
      params: this.buildUserListParams(params),
    });
  }

  createUser(request: CreateAdminUserRequest): Observable<ApiAdminUser> {
    return this.http.post<ApiAdminUser>('/api/admin/users', request);
  }

  getUser(userId: string): Observable<ApiAdminUser> {
    return this.http.get<ApiAdminUser>(`/api/admin/users/${userId}`);
  }

  updateUser(userId: string, request: UpdateAdminUserRequest): Observable<ApiAdminUser> {
    return this.http.patch<ApiAdminUser>(`/api/admin/users/${userId}`, request);
  }

  updateUserRole(userId: string, role: ApiUserRole): Observable<ApiAdminUser> {
    return this.http.patch<ApiAdminUser>(`/api/admin/users/${userId}/role`, { role });
  }

  updateUserStatus(userId: string, status: ApiAccountStatus): Observable<ApiAdminUser> {
    return this.http.patch<ApiAdminUser>(`/api/admin/users/${userId}/status`, { status });
  }

  logoutUser(userId: string): Observable<void> {
    return this.http.post<void>(`/api/admin/users/${userId}/logout-all`, null);
  }

  resendSetupEmail(userId: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(
      `/api/admin/users/${userId}/resend-setup-email`,
      null,
    );
  }

  deleteUser(userId: string): Observable<void> {
    return this.http.delete<void>(`/api/admin/users/${userId}`);
  }

  private buildUserListParams(params: ListAdminUsersParams): HttpParams {
    let httpParams = new HttpParams();

    if (params.search) {
      httpParams = httpParams.set('search', params.search);
    }
    if (params.role) {
      httpParams = httpParams.set('role', params.role);
    }
    if (params.status) {
      httpParams = httpParams.set('status', params.status);
    }
    if (params.limit !== undefined) {
      httpParams = httpParams.set('limit', params.limit);
    }
    if (params.offset !== undefined) {
      httpParams = httpParams.set('offset', params.offset);
    }

    return httpParams;
  }
}
