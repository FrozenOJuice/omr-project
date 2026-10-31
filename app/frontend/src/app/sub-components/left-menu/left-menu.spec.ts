import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal } from '@angular/core';
import { provideRouter, Router } from '@angular/router';
import { vi } from 'vitest';
import { of } from 'rxjs';
import { LeftMenu } from './left-menu';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../services/auth.service';
import { SiteBrandingService } from '../../services/site-branding.service';
import { DEFAULT_SITE_BRANDING } from '../../models/site-branding.model';

@Component({ template: '' })
class BlankPage {}

const testRoutes = [
  { path: 'admin',         component: BlankPage },
  { path: 'courses',       component: BlankPage },
  { path: 'regrade',       component: BlankPage },
  { path: 'notifications', component: BlankPage },
  { path: 'account',       component: BlankPage },
];

// Items visible to every user regardless of role
const BASE_LABELS = ['Courses', 'Re-grade Requests', 'Notifications', 'Account'];

const setup = async (
  role: string | null,
  institution: 'ubc' | 'generic' = 'ubc',
  logoUrl = DEFAULT_SITE_BRANDING.logo_url,
): Promise<ComponentFixture<LeftMenu>> => {
  const siteBranding = signal({
    ...DEFAULT_SITE_BRANDING,
    logo_url: logoUrl,
    is_custom_logo: logoUrl !== DEFAULT_SITE_BRANDING.logo_url,
  });

  await TestBed.configureTestingModule({
    imports: [LeftMenu],
    providers: [
      provideRouter(testRoutes),
      {
        provide: UserService,
        useValue: {
          role: vi.fn(() => role),
          clear: vi.fn(),
          currentUser: vi.fn(() => ({ institution })),
        },
      },
      { provide: AuthService, useValue: { logout: vi.fn(() => of(null)) } },
      {
        provide: SiteBrandingService,
        useValue: {
          branding: siteBranding,
          ensureLoaded: vi.fn(() => of(siteBranding())),
        },
      },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(LeftMenu);
  return fixture;
};

describe('LeftMenu', () => {

  // No role (unauthenticated / student)

  describe('with no role', () => {
    let fixture: ComponentFixture<LeftMenu>;
    let component: LeftMenu;

    beforeEach(async () => {
      localStorage.clear();
      fixture = await setup(null);
      component = fixture.componentInstance;
    });

    it('should create', () => {
      fixture.detectChanges();
      expect(component).toBeTruthy();
    });

    it('should start expanded', () => {
      expect(component.isCollapsed).toBe(false);
    });

    it('should show the Aperture logo when expanded', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.logo-wrapper app-aperture-logo')).not.toBeNull();
      expect(fixture.nativeElement.querySelector('.logo-wrapper .site-logo')).toBeNull();
    });

    it('should render 4 nav items for an unauthenticated user', () => {
      fixture.detectChanges();
      const items = fixture.nativeElement.querySelectorAll('a.menu-item');
      expect(items.length).toBe(4);
    });

    it('should render all base nav labels', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      BASE_LABELS.forEach(label => expect(labels).toContain(label));
    });

    it('should not show Admin panel for unauthenticated users', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      expect(labels).not.toContain('Admin');
    });

    it('should show labels when expanded', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('.menu-label').length).toBeGreaterThan(0);
    });

    it('should have a logout button', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.logout-btn')).not.toBeNull();
    });

    it('should render icons for every nav item', () => {
      fixture.detectChanges();
      const icons = fixture.nativeElement.querySelectorAll('a.menu-item .menu-icon');
      expect(icons.length).toBe(4);
    });

    it('should render an icon for the logout button', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.logout-btn .menu-icon')).not.toBeNull();
    });

    // Collapse toggle 

    it('should set isCollapsed to true when toggled', () => {
      component.toggle();
      expect(component.isCollapsed).toBe(true);
    });

    it('should add collapsed class to the host element when toggled', () => {
      component.toggle();
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.left-menu').classList.contains('collapsed')).toBe(true);
    });

    it('should hide the site logo when collapsed', () => {
      component.toggle();
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.logo-wrapper')).toBeNull();
    });

    it('should hide labels when collapsed', () => {
      component.toggle();
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('.menu-label').length).toBe(0);
    });

    it('should expand again when toggled twice', () => {
      component.toggle();
      component.toggle();
      expect(component.isCollapsed).toBe(false);
    });

    // Active route

    it('should mark the Notifications item as active when on /notifications', async () => {
      fixture.detectChanges();
      await TestBed.inject(Router).navigate(['/notifications']);
      fixture.detectChanges();
      const activeItems = fixture.nativeElement.querySelectorAll('a.menu-item.active');
      expect(activeItems.length).toBe(1);
      expect(activeItems[0].querySelector('.menu-label').textContent.trim()).toBe('Notifications');
    });

    it('should mark the Courses item as active when on /courses', async () => {
      fixture.detectChanges();
      await TestBed.inject(Router).navigate(['/courses']);
      fixture.detectChanges();
      const activeItems = fixture.nativeElement.querySelectorAll('a.menu-item.active');
      expect(activeItems.length).toBe(1);
      expect(activeItems[0].querySelector('.menu-label').textContent.trim()).toBe('Courses');
    });

    it('should not mark any item active when no route matches', async () => {
      fixture.detectChanges();
      await TestBed.inject(Router).navigate(['/']);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('a.menu-item.active').length).toBe(0);
    });
  });

  describe('with no institution branding', () => {
    let fixture: ComponentFixture<LeftMenu>;

    beforeEach(async () => {
      fixture = await setup('professor', 'generic');
      fixture.detectChanges();
    });

    it('still shows the product subtitle, which is not institution-specific', () => {
      const subtitle = fixture.nativeElement.querySelector('.menu-title-sub');
      expect(subtitle).not.toBeNull();
      expect(subtitle.textContent.trim()).toBe('By Aperture');
    });
  });

  describe('with a custom site logo', () => {
    it('shows the same custom logo for a generic institution user', async () => {
      const fixture = await setup('student', 'generic', '/api/site-branding/logo?v=123');
      fixture.detectChanges();

      const logo = fixture.nativeElement.querySelector('.site-logo');
      expect(logo.getAttribute('src')).toBe('/api/site-branding/logo?v=123');
      expect(fixture.nativeElement.querySelector('app-aperture-logo')).toBeNull();
    });
  });

  // Professor role
  describe('with professor role', () => {
    let fixture: ComponentFixture<LeftMenu>;

    beforeEach(async () => {
      fixture = await setup('professor');
    });

    it('should render 4 nav items for a professor', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('a.menu-item').length).toBe(4);
    });

    it('should not show Admin panel for a professor', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      expect(labels).not.toContain('Admin');
    });

    it('should show all base nav labels for a professor', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      BASE_LABELS.forEach(label => expect(labels).toContain(label));
    });
  });

  // Admin role

  describe('with admin role', () => {
    let fixture: ComponentFixture<LeftMenu>;

    beforeEach(async () => {
      fixture = await setup('admin');
    });

    it('should render 5 nav items for an admin', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('a.menu-item').length).toBe(5);
    });

    it('should show Admin panel for an admin', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      expect(labels).toContain('Admin');
    });

    it('should show all base nav labels for an admin', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      BASE_LABELS.forEach(label => expect(labels).toContain(label));
    });
  });

  // Student role

  describe('with student role', () => {
    let fixture: ComponentFixture<LeftMenu>;

    beforeEach(async () => {
      fixture = await setup('student');
    });

    it('should render 4 nav items for a student', () => {
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelectorAll('a.menu-item').length).toBe(4);
    });

    it('should not show Admin panel for a student', () => {
      fixture.detectChanges();
      const labels = Array.from(fixture.nativeElement.querySelectorAll('a.menu-item .menu-label'))
        .map((el: any) => el.textContent.trim());
      expect(labels).not.toContain('Admin');
    });
  });
});
