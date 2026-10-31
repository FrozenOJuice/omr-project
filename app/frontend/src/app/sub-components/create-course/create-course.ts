import { ChangeDetectorRef, Component, EventEmitter, inject, Input, OnChanges, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CourseService } from '../../services/course.service';
import { ApiCourse, Course } from '../../models/course.model';
import {
  ACADEMIC_TERM_YEAR_FORMAT_OPTIONS,
  AcademicTerm,
  AcademicTermYearFormat,
  academicTermYearFormatLabel,
  formatAcademicPeriod,
} from '../../models/academic-term.model';
import { InstitutionCode } from '../../models/institution.model';
import { AcademicTermService } from '../../services/academic-term.service';
import { extractApiErrorMessage } from '../../utils/api-error';

const COURSE_CODE_REGEX = /^[A-Z]{2,4} \d{2,4}[A-Z]?$/;
const MANAGE_TERMS_SELECTION = '__manage_terms__';

@Component({
  selector: 'app-create-course',
  imports: [FormsModule],
  templateUrl: './create-course.html',
  styleUrl: './create-course.css',
})
export class CreateCourse implements OnChanges, OnInit {
  private courseService = inject(CourseService);
  private academicTermService = inject(AcademicTermService);
  private cdr = inject(ChangeDetectorRef);

  @Input() editCourse: Course | null = null;
  @Input() institution: InstitutionCode = 'ubc';
  @Output() close = new EventEmitter<void>();
  @Output() created = new EventEmitter<ApiCourse>();
  @Output() updated = new EventEmitter<ApiCourse>();

  code = '';
  name = '';
  academicTerms: AcademicTerm[] = [];
  academicTermId = '';
  isLoadingTerms = true;
  termsError = '';
  academicYearStart = new Date().getFullYear();
  isLoading = false;
  error = '';
  readonly yearFormatOptions = ACADEMIC_TERM_YEAR_FORMAT_OPTIONS;
  showCustomTermDialog = false;
  customTermName = '';
  customTermYearFormat: AcademicTermYearFormat = 'start_year';
  customTermError = '';
  isCreatingCustomTerm = false;

  get isEditMode(): boolean {
    return this.editCourse !== null;
  }

  get codeValid(): boolean {
    return COURSE_CODE_REGEX.test(this.code.trim());
  }

  get canSubmit(): boolean {
    const minYear = this.isEditMode ? 2000 : new Date().getFullYear();
    return this.codeValid
      && this.name.trim().length > 0
      && this.academicTermId.length > 0
      && this.academicYearStart >= minYear
      && this.academicYearStart <= 2100;
  }

  get selectableTerms(): AcademicTerm[] {
    return this.academicTerms.filter(term => term.is_active || term.id === this.academicTermId);
  }

  get termInstitution(): InstitutionCode {
    return this.institution;
  }

  get canCreateCustomTerm(): boolean {
    return this.customTermName.trim().length > 0 && !this.isCreatingCustomTerm;
  }

  ngOnInit(): void {
    this.academicTermService.listTerms({
      institution: this.termInstitution,
      includeArchived: true,
    }).subscribe({
      next: terms => {
        this.academicTerms = this.withCurrentCourseTerm(terms);
        this.isLoadingTerms = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.academicTerms = this.withCurrentCourseTerm([]);
        this.isLoadingTerms = false;
        this.termsError = 'Unable to load academic terms.';
        this.cdr.markForCheck();
      },
    });
  }

  ngOnChanges(): void {
    if (this.editCourse) {
      this.code = this.editCourse.code;
      this.name = this.editCourse.name;
      this.academicTermId = this.editCourse.academicTerm.id;
      this.academicYearStart = this.editCourse.academicYearStart;
    } else {
      this.code = '';
      this.name = '';
      this.academicTermId = '';
      this.academicYearStart = new Date().getFullYear();
    }
    this.error = '';
    this.closeCustomTermDialog();
  }

  submit(): void {
    if (!this.canSubmit) return;
    this.isLoading = true;
    this.error = '';

    const obs = this.isEditMode
      ? this.courseService.updateCourse(
          this.editCourse!.id,
          this.code.trim(),
          this.name.trim(),
          this.academicYearStart,
          this.academicTermId === this.editCourse!.academicTerm.id ? undefined : this.academicTermId,
        )
      : this.courseService.createCourse(
          this.code.trim(),
          this.name.trim(),
          this.academicTermId,
          this.academicYearStart,
        );

    obs.subscribe({
      next: (course) => {
        this.isLoading = false;
        this.isEditMode ? this.updated.emit(course) : this.created.emit(course);
        this.cdr.markForCheck();
      },
      error: () => {
        this.isLoading = false;
        this.error = `Failed to ${this.isEditMode ? 'update' : 'create'} course. Please try again.`;
        this.cdr.markForCheck();
      },
    });
  }

  termLabel(term: AcademicTerm): string {
    return formatAcademicPeriod(term, this.academicYearStart);
  }

  isCurrentTermFromAnotherInstitution(term: AcademicTerm): boolean {
    return term.id === this.editCourse?.academicTerm.id
      && term.institution !== this.institution;
  }

  onTermSelection(value: string): void {
    if (value === MANAGE_TERMS_SELECTION) {
      this.openCustomTermDialog();
      return;
    }
    this.academicTermId = value;
  }

  yearFormatLabel(format: AcademicTermYearFormat): string {
    return academicTermYearFormatLabel(format, this.academicYearStart);
  }

  openCustomTermDialog(): void {
    this.customTermError = '';
    this.showCustomTermDialog = true;
  }

  closeCustomTermDialog(): void {
    if (this.isCreatingCustomTerm) return;
    this.showCustomTermDialog = false;
    this.customTermName = '';
    this.customTermYearFormat = 'start_year';
    this.customTermError = '';
  }

  createCustomTerm(): void {
    const name = this.customTermName.trim();
    if (!name || this.isCreatingCustomTerm) return;

    this.isCreatingCustomTerm = true;
    this.customTermError = '';
    this.academicTermService.createTerm({
      name,
      term_type: 'custom',
      institution: this.termInstitution,
      year_format: this.customTermYearFormat,
    }).subscribe({
      next: term => {
        this.academicTerms = [...this.academicTerms, term].sort((a, b) => {
          if (a.term_type !== b.term_type) return a.term_type === 'preset' ? -1 : 1;
          return a.name.localeCompare(b.name);
        });
        this.academicTermId = term.id;
        this.isCreatingCustomTerm = false;
        this.closeCustomTermDialog();
        this.cdr.markForCheck();
      },
      error: error => {
        this.customTermError = extractApiErrorMessage(error, 'Unable to create academic term.');
        this.isCreatingCustomTerm = false;
        this.cdr.markForCheck();
      },
    });
  }

  private withCurrentCourseTerm(terms: AcademicTerm[]): AcademicTerm[] {
    const currentTerm = this.editCourse?.academicTerm;
    if (!currentTerm || terms.some(term => term.id === currentTerm.id)) return terms;
    return [currentTerm, ...terms];
  }
}
