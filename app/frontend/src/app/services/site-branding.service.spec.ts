import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SiteBranding } from '../models/site-branding.model';
import { SiteBrandingService } from './site-branding.service';

const customBranding: SiteBranding = {
  logo_url: '/api/site-branding/logo?v=1',
  is_custom_logo: true,
};

describe('SiteBrandingService', () => {
  let service: SiteBrandingService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(SiteBrandingService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the public site branding once and shares it globally', () => {
    service.ensureLoaded().subscribe();
    const request = http.expectOne('/api/site-branding');
    request.flush(customBranding);

    service.ensureLoaded().subscribe((branding) => {
      expect(branding).toEqual(customBranding);
    });
    http.expectNone('/api/site-branding');
    expect(service.branding()).toEqual(customBranding);
  });

  it('uploads a logo as multipart data and updates shared branding', () => {
    const file = new File(['image'], 'logo.png', { type: 'image/png' });
    service.uploadLogo(file).subscribe();

    const request = http.expectOne('/api/admin/site-branding/logo');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toBeInstanceOf(FormData);
    expect((request.request.body as FormData).get('file')).toBe(file);
    request.flush(customBranding);

    expect(service.branding()).toEqual(customBranding);
  });

  it('restores the default logo and updates shared branding', () => {
    service.resetLogo().subscribe();

    const request = http.expectOne('/api/admin/site-branding/logo');
    expect(request.request.method).toBe('DELETE');
    request.flush({
      logo_url: '/ApertureLogoFull.svg',
      is_custom_logo: false,
    });

    expect(service.branding().is_custom_logo).toBe(false);
  });
});
