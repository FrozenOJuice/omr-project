import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { tap } from 'rxjs/operators';

import {
  DEFAULT_SITE_BRANDING,
  SiteBranding,
} from '../models/site-branding.model';

@Injectable({ providedIn: 'root' })
export class SiteBrandingService {
  private http = inject(HttpClient);
  private hasLoaded = false;

  readonly branding = signal<SiteBranding>(DEFAULT_SITE_BRANDING);

  ensureLoaded(): Observable<SiteBranding> {
    if (this.hasLoaded) return of(this.branding());
    return this.remember(this.http.get<SiteBranding>('/api/site-branding'));
  }

  uploadLogo(file: File): Observable<SiteBranding> {
    const form = new FormData();
    form.append('file', file);
    return this.remember(
      this.http.put<SiteBranding>('/api/admin/site-branding/logo', form),
    );
  }

  resetLogo(): Observable<SiteBranding> {
    return this.remember(
      this.http.delete<SiteBranding>('/api/admin/site-branding/logo'),
    );
  }

  private remember(request: Observable<SiteBranding>): Observable<SiteBranding> {
    return request.pipe(
      tap((branding) => {
        this.branding.set(branding);
        this.hasLoaded = true;
      }),
    );
  }
}
