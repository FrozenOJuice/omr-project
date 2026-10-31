import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { vi } from 'vitest';
import { Chart } from 'chart.js';
import { AdminDashboard } from './admin-dashboard';
import { AcademicTermService } from '../../services/academic-term.service';
import { of } from 'rxjs';
import { SiteBrandingService } from '../../services/site-branding.service';
import {
  DEFAULT_SITE_BRANDING,
  MAX_SITE_LOGO_BYTES,
  SiteBranding,
} from '../../models/site-branding.model';

vi.mock('chart.js', () => {
  class Chart {
    static defaults = { font: { family: '' } };
    static register = vi.fn();
    static instances: Chart[] = [];

    type: string;
    data: { datasets: Array<{ data: number[] }> };
    update = vi.fn();
    destroy = vi.fn();

    constructor(
      _canvas: HTMLCanvasElement,
      config: { type: string; data: { datasets: Array<{ data: number[] }> } }
    ) {
      this.type = config.type;
      this.data = config.data;
      Chart.instances.push(this);
    }
  }

  return { Chart, registerables: [] };
});

type MockChart = {
  type: string;
  data: { datasets: Array<{ data: number[] }> };
  update: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
};

function getMockCharts(): MockChart[] {
  return (Chart as unknown as { instances: MockChart[] }).instances;
}

describe('AdminDashboard', () => {
  let component: AdminDashboard;
  let fixture: ComponentFixture<AdminDashboard>;
  let branding: ReturnType<typeof signal<SiteBranding>>;
  let siteBrandingService: {
    branding: typeof branding;
    uploadLogo: ReturnType<typeof vi.fn>;
    resetLogo: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    getMockCharts().length = 0;
    vi.clearAllMocks();
    branding = signal({ ...DEFAULT_SITE_BRANDING });
    siteBrandingService = {
      branding,
      uploadLogo: vi.fn(() => {
        const updated = {
          ...DEFAULT_SITE_BRANDING,
          logo_url: '/api/site-branding/logo?v=1',
          is_custom_logo: true,
        };
        branding.set(updated);
        return of(updated);
      }),
      resetLogo: vi.fn(() => {
        branding.set({ ...DEFAULT_SITE_BRANDING });
        return of(branding());
      }),
    };

    await TestBed.configureTestingModule({
      imports: [AdminDashboard],
      providers: [
        {
          provide: AcademicTermService,
          useValue: {
            listTerms: vi.fn(() => of([])),
            createTerm: vi.fn(),
            updateTerm: vi.fn(),
            deleteTerm: vi.fn(),
          },
        },
        { provide: SiteBrandingService, useValue: siteBrandingService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminDashboard);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('renders preset-term management', () => {
    const manager = fixture.nativeElement.querySelector('app-academic-term-manager');
    expect(manager).not.toBeNull();
    expect(manager.textContent).toContain('Preset academic terms');
  });

  it('renders site-wide logo management', () => {
    const card = fixture.nativeElement.querySelector('.site-branding-card');
    expect(card.textContent).toContain('Site logo');
    expect(card.textContent).toContain('every user');
    expect(card.querySelector('.site-logo-preview img').getAttribute('src')).toBe('/ApertureLogoFull.svg');
  });

  it('rejects unsupported and oversized logo files before upload', () => {
    const unsupportedInput = { files: [new File(['text'], 'logo.svg', { type: 'image/svg+xml' })], value: 'logo.svg' };
    component.onLogoFileSelected({ target: unsupportedInput } as unknown as Event);
    expect(component.logoError).toContain('PNG, JPEG, or WebP');

    const oversizedInput = {
      files: [new File([new Uint8Array(MAX_SITE_LOGO_BYTES + 1)], 'large.png', { type: 'image/png' })],
      value: 'large.png',
    };
    component.onLogoFileSelected({ target: oversizedInput } as unknown as Event);
    expect(component.logoError).toContain('2 MB or smaller');

    component.uploadSiteLogo();
    expect(siteBrandingService.uploadLogo).not.toHaveBeenCalled();
  });

  it('uploads a selected logo without tying it to an institution', () => {
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'logo.png', { type: 'image/png' });
    component.onLogoFileSelected({ target: { files: [file], value: 'logo.png' } } as unknown as Event);
    component.uploadSiteLogo();

    expect(siteBrandingService.uploadLogo).toHaveBeenCalledWith(file);
    expect(component.logoNotice).toBe('Logo updated');
    expect(component.selectedLogoFile).toBeNull();
  });

  it('restores the default site logo', () => {
    component.resetSiteLogo();

    expect(siteBrandingService.resetLogo).toHaveBeenCalledTimes(1);
    expect(component.logoNotice).toBe('Default restored');
  });

  it('should initialize line, bar, and doughnut charts on first render', () => {
    expect(getMockCharts().map(chart => chart.type)).toEqual(['line', 'bar', 'doughnut']);
  });

  it('should destroy all chart instances on component teardown', () => {
    fixture.destroy();

    getMockCharts().forEach(chart => {
      expect(chart.destroy).toHaveBeenCalledTimes(1);
    });
  });

  it('ignores a save on another row while a user mutation is already in flight', () => {
    // A different row is mid-request; saving here must not proceed (and thus
    // not reassign busyUserId, which would desync the busy row's controls).
    component.busyUserId = 'busy-user';

    component.onSaveUser({
      userId: 'other-user',
      firstName: 'New',
      lastName: 'Name',
      email: 'other@ubc.ca',
      role: 'Student',
      status: 'active',
      studentNumber: null,
    });

    expect(component.busyUserId).toBe('busy-user');
  });
});
