import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CurrentUser, NotificationPreferences } from '../models/auth.model';
import { InstitutionCode } from '../models/institution.model';

@Injectable({
  providedIn: 'root',
})
export class Accounts {
  private http = inject(HttpClient);

  getMe(): Observable<CurrentUser> {
    return this.http.get<CurrentUser>('/api/auth/me');
  }

  changePassword(currentPassword: string, newPassword: string): Observable<void> {
    return this.http.post<void>('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
  }

  updateMe(
    firstName: string,
    lastName: string,
    email: string,
    studentNumber?: string,
    institution?: InstitutionCode,
  ): Observable<CurrentUser> {
    return this.http.patch<CurrentUser>('/api/auth/me', {
      first_name: firstName,
      last_name: lastName,
      email,
      student_number: studentNumber || null,
      institution,
    });
  }

  updateNotificationPreferences(preferences: NotificationPreferences): Observable<CurrentUser> {
    return this.http.patch<CurrentUser>('/api/auth/me/preferences', preferences);
  }
}
