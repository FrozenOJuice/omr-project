import { Component, inject, input, OnInit } from '@angular/core';
import { SiteBrandingService } from '../../services/site-branding.service';
import { ApertureLogo } from '../aperture-logo/aperture-logo';

@Component({
  selector: 'app-site-identity',
  imports: [ApertureLogo],
  templateUrl: './site-identity.html',
  styleUrl: './site-identity.css',
})
export class SiteIdentity implements OnInit {
  private readonly siteBrandingService = inject(SiteBrandingService);

  readonly size = input('85px');
  readonly siteBranding = this.siteBrandingService.branding;

  ngOnInit(): void {
    this.siteBrandingService.ensureLoaded().subscribe({ error: () => undefined });
  }
}
