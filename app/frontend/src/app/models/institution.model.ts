export type InstitutionCode = 'ubc' | 'generic';

export interface InstitutionBranding {
  code: InstitutionCode;
  name: string;
  navigationTitle: string;
  navigationSubtitle: string;
}

// Product branding is site-wide and may be replaced by an administrator, so
// it intentionally does not vary by institution.
export const INSTITUTION_BRANDING: Readonly<Record<InstitutionCode, InstitutionBranding>> = {
  ubc: {
    code: 'ubc',
    name: 'University of British Columbia',
    navigationTitle: 'OMR System',
    navigationSubtitle: 'By Aperture',
  },
  generic: {
    code: 'generic',
    name: 'None',
    navigationTitle: 'OMR System',
    navigationSubtitle: 'By Aperture',
  },
};

export const INSTITUTION_OPTIONS = Object.values(INSTITUTION_BRANDING);

export function getInstitutionBranding(
  institution: string | null | undefined,
): InstitutionBranding {
  if (institution === 'generic') {
    return INSTITUTION_BRANDING.generic;
  }

  return INSTITUTION_BRANDING.ubc;
}
