import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';

import { AcademicTerm } from '../../models/academic-term.model';
import { AcademicTermService } from '../../services/academic-term.service';
import { AcademicTermManager } from './academic-term-manager';

const customTerm: AcademicTerm = {
  id: 'custom-1', institution: 'ubc', code: null, name: 'Fall Intensive',
  term_type: 'custom', year_format: 'start_year', is_active: true, in_use: false,
  created_by: 'professor-1', created_at: '', updated_at: '',
};

const presetTerm: AcademicTerm = {
  ...customTerm, id: 'preset-1', code: 'winter-session-1',
  name: 'Winter Session 1', term_type: 'preset', created_by: null,
  year_format: 'academic_year_range',
};

describe('AcademicTermManager', () => {
  let component: AcademicTermManager;
  let fixture: ComponentFixture<AcademicTermManager>;
  const service = {
    listTerms: vi.fn(() => of([presetTerm, customTerm])),
    createTerm: vi.fn(() => of(customTerm)),
    updateTerm: vi.fn(() => of({ ...customTerm, is_active: false })),
    deleteTerm: vi.fn(() => of(undefined)),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    service.listTerms.mockReturnValue(of([presetTerm, customTerm]));
    service.createTerm.mockReturnValue(of(customTerm));
    service.updateTerm.mockReturnValue(of({ ...customTerm, is_active: false }));
    service.deleteTerm.mockReturnValue(of(undefined));

    await TestBed.configureTestingModule({
      imports: [AcademicTermManager],
      providers: [{ provide: AcademicTermService, useValue: service }],
    }).compileComponents();

    fixture = TestBed.createComponent(AcademicTermManager);
    component = fixture.componentInstance;
  });

  it('shows only custom terms in account mode', () => {
    fixture.componentRef.setInput('mode', 'custom');
    fixture.detectChanges();

    expect(component.terms).toEqual([customTerm]);
    expect(fixture.nativeElement.textContent).toContain('Fall Intensive');
    expect(fixture.nativeElement.textContent).not.toContain('Winter Session 1');
  });

  it('creates an owner-scoped custom term', () => {
    fixture.componentRef.setInput('mode', 'custom');
    fixture.componentRef.setInput('institution', 'ubc');
    fixture.detectChanges();
    component.newName = ' Reading Week ';
    component.newYearFormat = 'none';

    component.createTerm();

    expect(service.createTerm).toHaveBeenCalledWith({
      name: 'Reading Week',
      term_type: 'custom',
      institution: 'ubc',
      year_format: 'none',
    });
  });

  it('loads and creates presets for the selected institution in admin mode', () => {
    fixture.componentRef.setInput('mode', 'preset');
    fixture.componentRef.setInput('allowInstitutionSelection', true);
    fixture.detectChanges();
    component.onInstitutionChange('generic');
    component.newName = 'Trimester 1';
    component.createTerm();

    expect(service.listTerms).toHaveBeenLastCalledWith({
      institution: 'generic',
      includeArchived: true,
    });
    expect(service.createTerm).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Trimester 1',
      term_type: 'preset',
      institution: 'generic',
    }));
  });

  it('archives a term through the update API', () => {
    fixture.detectChanges();
    component.toggleActive(customTerm);

    expect(service.updateTerm).toHaveBeenCalledWith(customTerm.id, { is_active: false });
  });

  it('uses an in-app confirmation dialog before deleting a custom term', () => {
    fixture.detectChanges();
    component.requestDeleteTerm(customTerm);

    expect(service.deleteTerm).not.toHaveBeenCalled();
    expect(component.deleteConfirmationTerm).toEqual(customTerm);

    component.confirmDeleteTerm();

    expect(service.deleteTerm).toHaveBeenCalledWith(customTerm.id);
    expect(component.deleteConfirmationTerm).toBeNull();
  });

  it('can cancel custom-term deletion without calling the API', () => {
    fixture.detectChanges();
    component.requestDeleteTerm(customTerm);

    component.cancelDeleteTerm();

    expect(component.deleteConfirmationTerm).toBeNull();
    expect(service.deleteTerm).not.toHaveBeenCalled();
  });

  it('immediately explains why an in-use term cannot be deleted', () => {
    const usedTerm = { ...customTerm, in_use: true };
    service.listTerms.mockReturnValueOnce(of([usedTerm]));
    fixture.detectChanges();

    const deleteButton: HTMLButtonElement = fixture.nativeElement.querySelector('.action-btn--danger');
    deleteButton.click();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Term cannot be deleted');
    expect(fixture.nativeElement.textContent).toContain('being used by one or more courses');
    expect(fixture.nativeElement.textContent).not.toContain('Delete term');
    expect(service.deleteTerm).not.toHaveBeenCalled();
  });

  it('renders terms in the bounded grid layout with compact edit controls', () => {
    fixture.detectChanges();
    component.startEdit(customTerm);

    expect(fixture.nativeElement.querySelector('.term-list')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.term-row')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.term-name-field')).not.toBeNull();
    expect(component.editingTermId).toBe(customTerm.id);
  });

  it('shows backend errors', () => {
    service.createTerm.mockReturnValueOnce(throwError(() => ({
      error: { error: { message: 'An academic term with this name already exists' } },
    })));
    fixture.detectChanges();
    component.newName = 'Duplicate';
    component.createTerm();

    expect(component.error).toBe('An academic term with this name already exists');
  });
});
