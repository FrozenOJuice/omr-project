import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { vi } from 'vitest';

import { Course } from '../../../../models/course.model';
import { RetentionPolicy, RetentionPolicyStatus } from '../../../../models/retention-policy.model';
import { CourseService } from '../../../../services/course.service';
import { RetentionPolicyModal } from './retention-policy-modal';


const COURSE: Course = {
  id: 'course-1',
  code: 'COSC 499',
  name: 'Capstone',
  students: 12,
  studentList: [],
  academicTerm: {
    id: 'winter-2', institution: 'ubc', code: 'winter-session-2',
    name: 'Winter Session 2', term_type: 'preset', year_format: 'academic_year_range',
    is_active: true, created_by: null, created_at: '', updated_at: '',
  },
  academicYearStart: 2026,
  archivedAt: null,
  exams: [],
  inviteLink: 'invite',
  source: 'omr',
  canvasLink: null,
  canManageCanvas: false,
};

const POLICY: RetentionPolicy = {
  id: 'policy-1',
  owner_user_id: 'professor-1',
  scanned_image_retention_months: 12,
  exam_record_retention_months: 12,
  retain_anonymized_analytics: true,
  source: 'ubc_default',
  created_at: '2026-07-19T00:00:00Z',
  updated_at: '2026-07-19T00:00:00Z',
};

const RECOMMENDED = {
  scanned_image_retention_months: 12,
  exam_record_retention_months: 12,
  retain_anonymized_analytics: true,
  maximum_retention_months: 72,
  basis: 'UBC Records Schedules TL7300-15 and TL7100-25',
  source_urls: ['https://recordsmanagement.ubc.ca/'],
};

const configuredStatus = (): RetentionPolicyStatus => ({
  configured: true,
  policy: POLICY,
  recommended: RECOMMENDED,
});

const unconfiguredStatus = (): RetentionPolicyStatus => ({
  configured: false,
  policy: null,
  recommended: RECOMMENDED,
});


describe('RetentionPolicyModal', () => {
  let fixture: ComponentFixture<RetentionPolicyModal>;
  let component: RetentionPolicyModal;

  const courseService = {
    getRetentionPolicy: vi.fn(() => of(configuredStatus())),
    upsertRetentionPolicy: vi.fn(() => of(POLICY)),
    archiveCourse: vi.fn(() => of({})),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    courseService.getRetentionPolicy.mockReturnValue(of(configuredStatus()));
    courseService.upsertRetentionPolicy.mockReturnValue(of(POLICY));
    courseService.archiveCourse.mockReturnValue(of({}));

    await TestBed.configureTestingModule({
      imports: [RetentionPolicyModal],
      providers: [{ provide: CourseService, useValue: courseService }],
    }).compileComponents();

    fixture = TestBed.createComponent(RetentionPolicyModal);
    fixture.componentRef.setInput('course', COURSE);
    component = fixture.componentInstance;
  });

  it('shows Yes, No, and Change Retention Policy when a policy exists', () => {
    fixture.detectChanges();

    expect(component.mode).toBe('confirm');
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Are you sure?');
    expect(text).toContain('Change Retention Policy');
    expect(text).toContain('Yes');
    expect(text).toContain('No');
  });

  it('renders the confirmation after an asynchronous policy response', async () => {
    const status = new Subject<RetentionPolicyStatus>();
    courseService.getRetentionPolicy.mockReturnValueOnce(status.asObservable());
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Loading retention policy');

    status.next(configuredStatus());
    await fixture.whenStable();

    expect(fixture.nativeElement.textContent).toContain('Are you sure?');
  });

  it('asks for the UBC-backed policy before the first archive', () => {
    courseService.getRetentionPolicy.mockReturnValueOnce(of(unconfiguredStatus()));
    fixture.detectChanges();

    expect(component.mode).toBe('configure');
    expect(component.draft.scanned_image_retention_months).toBe(12);
    expect(component.draft.exam_record_retention_months).toBe(12);
    expect(fixture.nativeElement.textContent).toContain('Set Retention Policy');
    expect(fixture.nativeElement.textContent).toContain('UBC default');
  });

  it('saves the first policy and archives with explicit confirmation', () => {
    courseService.getRetentionPolicy.mockReturnValueOnce(of(unconfiguredStatus()));
    const archived = vi.fn();
    component.archived.subscribe(archived);
    fixture.detectChanges();

    component.savePolicy();

    expect(courseService.upsertRetentionPolicy).toHaveBeenCalledWith({
      scanned_image_retention_months: 12,
      exam_record_retention_months: 12,
      retain_anonymized_analytics: true,
    });
    expect(courseService.archiveCourse).toHaveBeenCalledWith('course-1', true, false);
    expect(archived).toHaveBeenCalled();
  });

  it('archives with explicit confirmation when the professor selects Yes', () => {
    const archived = vi.fn();
    component.archived.subscribe(archived);
    fixture.detectChanges();

    component.confirmArchive();

    expect(courseService.archiveCourse).toHaveBeenCalledWith('course-1', true, false);
    expect(archived).toHaveBeenCalled();
  });

  it('changes the policy without archiving until Yes is selected', () => {
    fixture.detectChanges();
    component.changePolicy();
    component.draft.scanned_image_retention_months = 24;

    component.savePolicy();

    expect(courseService.upsertRetentionPolicy).toHaveBeenCalledWith({
      scanned_image_retention_months: 24,
      exam_record_retention_months: 12,
      retain_anonymized_analytics: true,
    });
    expect(courseService.archiveCourse).not.toHaveBeenCalled();
    expect(component.mode).toBe('confirm');
  });

  it('requires a second explicit action to override active course blockers', () => {
    const archived = vi.fn();
    component.archived.subscribe(archived);
    courseService.archiveCourse
      .mockReturnValueOnce(throwError(() => ({
        error: { error: { code: 'course_still_active' } },
      })))
      .mockReturnValueOnce(of({}));
    fixture.detectChanges();

    component.confirmArchive();

    expect(component.requiresActiveOverride).toBe(true);
    expect(component.error).toContain('unfinished exams');
    expect(courseService.archiveCourse).toHaveBeenLastCalledWith('course-1', true, false);

    component.confirmArchive();

    expect(courseService.archiveCourse).toHaveBeenLastCalledWith('course-1', true, true);
    expect(archived).toHaveBeenCalled();
  });
});
