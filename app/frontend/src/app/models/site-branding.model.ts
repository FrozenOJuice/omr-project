export interface SiteBranding {
  logo_url: string;
  is_custom_logo: boolean;
}

export const DEFAULT_SITE_BRANDING: SiteBranding = {
  logo_url: '/ApertureLogoFull.svg',
  is_custom_logo: false,
};

export const MAX_SITE_LOGO_BYTES = 2 * 1024 * 1024;
export const SITE_LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const;
export const SITE_LOGO_ACCEPT = SITE_LOGO_TYPES.join(',');
