import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-logout-all-devices',
  imports: [],
  templateUrl: './logout-all-devices.html',
  styleUrl: './logout-all-devices.css',
})
export class LogoutAllDevices {
  private authService = inject(AuthService);
  private router = inject(Router);

  isLoading = false;

  logoutAll() {
    this.isLoading = true;
    this.authService.logoutAll().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => this.router.navigate(['/login']),
    });
  }
}
