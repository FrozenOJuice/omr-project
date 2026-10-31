import { Component, inject, computed, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { UserService } from '../../services/user.service';
import { NotificationService } from '../../services/notification.service';
import { getInstitutionBranding } from '../../models/institution.model';
import { SiteBrandingService } from '../../services/site-branding.service';
import { ApertureLogo } from '../aperture-logo/aperture-logo';

@Component({
  selector: 'app-left-menu',
  imports: [RouterLink, RouterLinkActive, ApertureLogo],
  templateUrl: './left-menu.html',
  styleUrl: './left-menu.css',
})
export class LeftMenu implements OnInit {
  private authService = inject(AuthService);
  private userService = inject(UserService);
  private router = inject(Router);
  private notificationService = inject(NotificationService);
  private siteBrandingService = inject(SiteBrandingService);

  unreadCount = this.notificationService.unreadCount;
  siteBranding = this.siteBrandingService.branding;
  branding = computed(() =>
    getInstitutionBranding(this.userService.currentUser()?.institution),
  );

  private static readonly COLLAPSED_STORAGE_KEY = 'leftMenu:collapsed';

  isCollapsed = localStorage.getItem(LeftMenu.COLLAPSED_STORAGE_KEY) === 'true';

  ngOnInit(): void {
    this.siteBrandingService.ensureLoaded().subscribe({ error: () => undefined });
  }

  toggle() {
    this.isCollapsed = !this.isCollapsed;
    localStorage.setItem(LeftMenu.COLLAPSED_STORAGE_KEY, String(this.isCollapsed));
  }

  logout() {
    this.userService.clear();
    this.authService.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => this.router.navigate(['/login']),
    });
  }

  private readonly allMenuItems = [
    { label: 'Admin',             icon: 'admin_panel_settings', route: '/admin',         roles: ['admin'] },
    { label: 'Courses',           icon: 'assignment',           route: '/courses',       roles: null },
    { label: 'Re-grade Requests', icon: 'replay',               route: '/regrade',       roles: null },
    { label: 'Notifications',     icon: 'notifications',        route: '/notifications', roles: null },
    { label: 'Account',           icon: 'person',               route: '/account',       roles: null },
  ];

  menuItems = computed(() => {
    const role = this.userService.role();
    return this.allMenuItems.filter(item => !item.roles || (role && item.roles.includes(role)));
  });
}
