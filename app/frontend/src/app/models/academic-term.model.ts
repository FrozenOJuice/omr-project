import { InstitutionCode } from './institution.model';

export type AcademicTermType = 'preset' | 'custom';
export type AcademicTermYearFormat =
  | 'academic_year_range'
  | 'following_year'
  | 'start_year'
  | 'none';

export interface AcademicTerm {
  id: string;
  institution: InstitutionCode;
  code: string | null;
  name: string;
  term_type: AcademicTermType;
  year_format: AcademicTermYearFormat;
  is_active: boolean;
  in_use?: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateAcademicTermRequest {
  name: string;
  term_type: AcademicTermType;
  institution?: InstitutionCode;
  year_format: AcademicTermYearFormat;
}

export interface UpdateAcademicTermRequest {
  name?: string;
  year_format?: AcademicTermYearFormat;
  is_active?: boolean;
}

export const ACADEMIC_TERM_YEAR_FORMAT_OPTIONS: ReadonlyArray<{
  value: AcademicTermYearFormat;
  label: string;
}> = [
  { value: 'academic_year_range', label: 'Academic year (2026/27)' },
  { value: 'following_year', label: 'Following year (2027)' },
  { value: 'start_year', label: 'Starting year (2026)' },
  { value: 'none', label: 'No year' },
];

export function academicTermYearFormatLabel(
  format: AcademicTermYearFormat,
  academicYearStart = 2026,
): string {
  switch (format) {
    case 'academic_year_range':
      return `Academic year (${academicYearStart}/${String(academicYearStart + 1).slice(-2)})`;
    case 'following_year':
      return `Following year (${academicYearStart + 1})`;
    case 'start_year':
      return `Starting year (${academicYearStart})`;
    case 'none':
      return 'No year';
  }
}

export function formatAcademicPeriod(
  term: Pick<AcademicTerm, 'name' | 'year_format'>,
  academicYearStart: number,
): string {
  switch (term.year_format) {
    case 'academic_year_range':
      return `${term.name} ${academicYearStart}/${String(academicYearStart + 1).slice(-2)}`;
    case 'following_year':
      return `${term.name} ${academicYearStart + 1}`;
    case 'start_year':
      return `${term.name} ${academicYearStart}`;
    case 'none':
      return term.name;
  }
}
