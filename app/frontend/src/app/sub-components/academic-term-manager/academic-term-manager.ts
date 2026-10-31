import { ChangeDetectorRef, Component, Input, OnChanges, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  ACADEMIC_TERM_YEAR_FORMAT_OPTIONS,
  AcademicTerm,
  AcademicTermType,
  AcademicTermYearFormat,
  academicTermYearFormatLabel,
} from '../../models/academic-term.model';
import { INSTITUTION_OPTIONS, InstitutionCode } from '../../models/institution.model';
import { AcademicTermService } from '../../services/academic-term.service';
import { extractApiErrorMessage } from '../../utils/api-error';

@Component({
  selector: 'app-academic-term-manager',
  imports: [FormsModule],
  templateUrl: './academic-term-manager.html',
  styleUrl: './academic-term-manager.css',
})
export class AcademicTermManager implements OnInit, OnChanges {
  @Input() mode: AcademicTermType = 'custom';
  @Input() institution: InstitutionCode = 'ubc';
  @Input() allowInstitutionSelection = false;

  private termService = inject(AcademicTermService);
  private cdr = inject(ChangeDetectorRef);
  private initialized = false;

  readonly institutionOptions = INSTITUTION_OPTIONS;
  readonly yearFormatOptions = ACADEMIC_TERM_YEAR_FORMAT_OPTIONS;
  readonly yearFormatLabel = academicTermYearFormatLabel;

  selectedInstitution: InstitutionCode = 'ubc';
  terms: AcademicTerm[] = [];
  isLoading = false;
  error = '';
  operationTermId: string | null = null;

  newName = '';
  newYearFormat: AcademicTermYearFormat = 'start_year';
  isCreating = false;

  editingTermId: string | null = null;
  editName = '';
  editYearFormat: AcademicTermYearFormat = 'start_year';
  deleteConfirmationTerm: AcademicTerm | null = null;

  get title(): string {
    return this.mode === 'preset' ? 'Preset academic terms' : 'Custom academic terms';
  }

  get description(): string {
    return this.mode === 'preset'
      ? 'Manage the term choices available to users at each institution.'
      : 'Create term choices for your courses when the presets do not fit.';
  }

  get canCreate(): boolean {
    return this.newName.trim().length > 0 && !this.isCreating;
  }

  ngOnInit(): void {
    this.selectedInstitution = this.institution;
    this.initialized = true;
    this.loadTerms();
  }

  ngOnChanges(): void {
    if (!this.initialized) return;
    if (this.selectedInstitution === this.institution) return;
    this.selectedInstitution = this.institution;
    this.loadTerms();
  }

  onInstitutionChange(institution: InstitutionCode): void {
    this.selectedInstitution = institution;
    this.cancelEdit();
    this.cancelDeleteTerm();
    this.loadTerms();
  }

  loadTerms(): void {
    this.isLoading = true;
    this.error = '';
    this.termService.listTerms({
      institution: this.allowInstitutionSelection ? this.selectedInstitution : undefined,
      includeArchived: true,
    }).subscribe({
      next: terms => {
        this.terms = terms.filter(term => term.term_type === this.mode);
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: error => {
        this.error = extractApiErrorMessage(error, 'Unable to load academic terms.');
        this.isLoading = false;
        this.cdr.markForCheck();
      },
    });
  }

  createTerm(): void {
    const name = this.newName.trim();
    if (!name || this.isCreating) return;

    this.isCreating = true;
    this.error = '';
    this.termService.createTerm({
      name,
      term_type: this.mode,
      institution: this.selectedInstitution,
      year_format: this.newYearFormat,
    }).subscribe({
      next: term => {
        this.terms = [...this.terms, term].sort((a, b) => a.name.localeCompare(b.name));
        this.newName = '';
        this.isCreating = false;
        this.cdr.markForCheck();
      },
      error: error => {
        this.error = extractApiErrorMessage(error, 'Unable to create academic term.');
        this.isCreating = false;
        this.cdr.markForCheck();
      },
    });
  }

  startEdit(term: AcademicTerm): void {
    this.editingTermId = term.id;
    this.editName = term.name;
    this.editYearFormat = term.year_format;
    this.error = '';
  }

  cancelEdit(): void {
    this.editingTermId = null;
    this.editName = '';
  }

  saveEdit(term: AcademicTerm): void {
    const name = this.editName.trim();
    if (!name || this.operationTermId) return;
    this.operationTermId = term.id;
    this.error = '';
    this.termService.updateTerm(term.id, {
      name,
      year_format: this.editYearFormat,
    }).subscribe({
      next: updated => {
        this.replaceTerm(updated);
        this.operationTermId = null;
        this.cancelEdit();
        this.cdr.markForCheck();
      },
      error: error => this.failOperation(error, 'Unable to update academic term.'),
    });
  }

  toggleActive(term: AcademicTerm): void {
    if (this.operationTermId) return;
    this.operationTermId = term.id;
    this.error = '';
    this.termService.updateTerm(term.id, { is_active: !term.is_active }).subscribe({
      next: updated => {
        this.replaceTerm(updated);
        this.operationTermId = null;
        this.cdr.markForCheck();
      },
      error: error => this.failOperation(
        error,
        `Unable to ${term.is_active ? 'archive' : 'activate'} academic term.`,
      ),
    });
  }

  requestDeleteTerm(term: AcademicTerm): void {
    if (this.mode !== 'custom' || this.operationTermId) return;
    this.deleteConfirmationTerm = term;
    this.error = '';
  }

  cancelDeleteTerm(): void {
    if (this.operationTermId === this.deleteConfirmationTerm?.id) return;
    this.deleteConfirmationTerm = null;
  }

  confirmDeleteTerm(): void {
    const term = this.deleteConfirmationTerm;
    if (!term || term.in_use || this.mode !== 'custom' || this.operationTermId) return;

    this.operationTermId = term.id;
    this.error = '';
    this.termService.deleteTerm(term.id).subscribe({
      next: () => {
        this.terms = this.terms.filter(item => item.id !== term.id);
        this.operationTermId = null;
        this.deleteConfirmationTerm = null;
        this.cdr.markForCheck();
      },
      error: error => {
        if (this.isTermInUseError(error)) {
          this.operationTermId = null;
          this.deleteConfirmationTerm = { ...term, in_use: true };
          this.cdr.markForCheck();
          return;
        }
        this.deleteConfirmationTerm = null;
        this.failOperation(error, 'Unable to delete academic term.');
      },
    });
  }

  private replaceTerm(updated: AcademicTerm): void {
    this.terms = this.terms.map(term => term.id === updated.id
      ? { ...updated, in_use: updated.in_use ?? term.in_use }
      : term);
  }

  private isTermInUseError(error: unknown): boolean {
    return (error as { error?: { error?: { code?: string } } } | null)?.error?.error?.code
      === 'academic_term_in_use';
  }

  private failOperation(error: unknown, fallback: string): void {
    this.error = extractApiErrorMessage(error, fallback);
    this.operationTermId = null;
    this.cdr.markForCheck();
  }
}
