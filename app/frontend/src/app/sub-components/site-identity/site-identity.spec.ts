import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { SiteIdentity } from './site-identity';
import { SiteBrandingService } from '../../services/site-branding.service';
import { DEFAULT_SITE_BRANDING } from '../../models/site-branding.model';

describe('SiteIdentity', () => {
  let fixture: ComponentFixture<SiteIdentity>;
  const branding = signal({ ...DEFAULT_SITE_BRANDING });
  const ensureLoaded = vi.fn(() => of(branding()));

  beforeEach(async () => {
    branding.set({ ...DEFAULT_SITE_BRANDING });
    ensureLoaded.mockClear();

    await TestBed.configureTestingModule({
      imports: [SiteIdentity],
      providers: [{
        provide: SiteBrandingService,
        useValue: { branding, ensureLoaded },
      }],
    }).compileComponents();

    fixture = TestBed.createComponent(SiteIdentity);
    fixture.detectChanges();
  });

  it('shows the animated Aperture identity by default', () => {
    expect(ensureLoaded).toHaveBeenCalledTimes(1);
    expect(fixture.nativeElement.querySelector('app-aperture-logo')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.site-logo')).toBeNull();
  });

  it('replaces Aperture with the site-wide custom logo', () => {
    branding.set({
      logo_url: '/api/site-branding/logo?v=123',
      is_custom_logo: true,
    });
    fixture.detectChanges();

    const logo = fixture.nativeElement.querySelector('.site-logo');
    expect(logo.getAttribute('src')).toBe('/api/site-branding/logo?v=123');
    expect(logo.getAttribute('alt')).toBe('OMR System logo');
    expect(fixture.nativeElement.querySelector('app-aperture-logo')).toBeNull();
  });
});
