import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { AddStudentsModal } from './add-students-modal';
import { CourseService } from '../../services/course.service';
import { Course } from '../../models/course.model';

const futureExpiry = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();

const mockCourse: Course = {
  id: 'course-1',
  code: 'CS 101',
  name: 'Intro to CS',
  students: 0,
  studentList: [],
  academicTerm: {
    id: 'term-1', institution: 'ubc', code: null, name: 'S2026',
    term_type: 'custom', year_format: 'none', is_active: true,
    created_by: 'professor-1', created_at: '', updated_at: '',
  },
  academicYearStart: 2026,
  archivedAt: null,
  source: 'omr',
  canvasLink: null,
  canManageCanvas: false,
  inviteLink: 'abc123',
  inviteLinkExpiresAt: futureExpiry,
  exams: [],
};

const mockCourseService = {
  addStudent: vi.fn(),
  regenerateInviteLink: vi.fn(),
  uploadStudentsCsv: vi.fn(),
  resendInvites: vi.fn(),
};

describe('AddStudentsModal', () => {
  let component: AddStudentsModal;
  let fixture: ComponentFixture<AddStudentsModal>;
  let writeText: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.clearAllMocks();
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await TestBed.configureTestingModule({
      imports: [AddStudentsModal],
      providers: [{ provide: CourseService, useValue: mockCourseService }],
    }).compileComponents();

    fixture = TestBed.createComponent(AddStudentsModal);
    component = fixture.componentInstance;
    component.course = { ...mockCourse };
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialise inviteLink from course on init', () => {
    expect(component.inviteLink).toBe('abc123');
    expect(component.inviteLinkExpiresAt).toBe(futureExpiry);
  });

  it('should switch active tab', () => {
    component.selectTab('csv');
    expect(component.activeTab).toBe('csv');
    component.selectTab('link');
    expect(component.activeTab).toBe('link');
  });

  it('addStudent should emit studentsAdded and reset form on success', () => {
    const addedStudent = {
      id: 'student-1',
      userId: null,
      firstName: 'Ada',
      lastName: 'Lovelace',
      email: 'ada@example.com',
      studentNumber: '12345678',
      accountStatus: 'pending' as const,
      source: 'manual' as const,
      active: true,
    };
    mockCourseService.addStudent.mockReturnValue(of(addedStudent));
    component.firstName = ' Ada ';
    component.lastName = ' Lovelace ';
    component.email = ' ADA@EXAMPLE.COM ';
    component.studentNumber = '12345678';
    const emitSpy = vi.spyOn(component.studentsAdded, 'emit');

    component.addStudent();

    expect(mockCourseService.addStudent).toHaveBeenCalledWith('course-1', {
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
      student_number: '12345678',
    });
    expect(component.addedStudent).toEqual(addedStudent);
    expect(component.firstName).toBe('');
    expect(component.lastName).toBe('');
    expect(component.email).toBe('');
    expect(component.studentNumber).toBe('');
    expect(emitSpy).toHaveBeenCalledWith(1);
    expect(component.isAdding).toBeFalsy();
  });

  it('addStudent should validate student number before calling the service', () => {
    component.firstName = 'Ada';
    component.lastName = 'Lovelace';
    component.email = 'ada@example.com';
    component.studentNumber = '123';

    component.addStudent();

    expect(component.addError).toBe('Student number must be exactly 8 digits.');
    expect(mockCourseService.addStudent).not.toHaveBeenCalled();
  });

  it('joinUrl should include origin and invite link', () => {
    expect(component.joinUrl).toContain('/join/abc123');
  });

  it('joinUrl should be empty when inviteLink is empty', () => {
    component.inviteLink = '';
    expect(component.joinUrl).toBe('');
  });

  it('shows when the invite link expires', () => {
    component.selectTab('link');
    fixture.detectChanges();

    const status = fixture.nativeElement.querySelector(
      '[data-testid="invite-expiry-status"]',
    );
    const detail = fixture.nativeElement.querySelector(
      '[data-testid="invite-expiry-detail"]',
    );

    expect(status.textContent).toContain('Expires in 7 days');
    expect(detail.textContent).toContain('Valid until');
  });

  it('marks expired links and prevents copying them', () => {
    component.inviteLinkExpiresAt = new Date(Date.now() - 60_000).toISOString();
    component.selectTab('link');
    fixture.detectChanges();

    const status = fixture.nativeElement.querySelector(
      '[data-testid="invite-expiry-status"]',
    );
    const copyButton = fixture.nativeElement.querySelector('.link-display button');

    expect(status.textContent).toContain('Invite link expired');
    expect(copyButton.disabled).toBe(true);
    copyButton.click();
    expect(writeText).not.toHaveBeenCalled();
  });

  it('shows copied feedback after the first link copy', async () => {
    component.selectTab('link');
    fixture.detectChanges();

    fixture.nativeElement.querySelector('.link-display button').click();
    await fixture.whenStable();

    expect(writeText).toHaveBeenCalledWith(component.joinUrl);
    expect(fixture.nativeElement.querySelector('.link-display button').textContent).toContain('Copied!');
  });

  it('regenerateLink should update inviteLink on success', () => {
    const newExpiry = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
    mockCourseService.regenerateInviteLink.mockReturnValue(
      of({
        course_id: 'course-1',
        invite_link: 'newlink',
        invite_link_expires_at: newExpiry,
      }),
    );
    component.regenerateLink();
    expect(component.inviteLink).toBe('newlink');
    expect(component.inviteLinkExpiresAt).toBe(newExpiry);
    expect(component.course.inviteLink).toBe('newlink');
    expect(component.course.inviteLinkExpiresAt).toBe(newExpiry);
    expect(component.isRegenerating).toBeFalsy();
    expect(component.regenerateError).toBe('');
  });

  it('regenerateLink should set error on failure', () => {
    mockCourseService.regenerateInviteLink.mockReturnValue(throwError(() => new Error()));
    component.regenerateLink();
    expect(component.regenerateError).toBeTruthy();
    expect(component.isRegenerating).toBeFalsy();
  });

  it('onFileChange should set csvFile', () => {
    const file = new File(['a,b'], 'students.csv', { type: 'text/csv' });
    const event = { target: { files: [file] } } as unknown as Event;
    component.onFileChange(event);
    expect(component.csvFile).toBe(file);
    expect(component.uploadResult).toBeNull();
    expect(component.uploadError).toBe('');
  });

  it('uploadCsv should emit studentsAdded and set result on success', () => {
    const result = {
      enrolled: 3,
      linked: 1,
      pending: 2,
      skipped: 1,
      invited: 2,
      invite_failed: 0,
      warnings: [],
      errors: [],
    };
    mockCourseService.uploadStudentsCsv.mockReturnValue(of(result));
    component.csvFile = new File([''], 'students.csv');
    const emitSpy = vi.spyOn(component.studentsAdded, 'emit');
    component.uploadCsv();
    expect(component.uploadResult).toEqual(result);
    expect(emitSpy).toHaveBeenCalledWith(3);
    expect(component.isUploading).toBeFalsy();
  });

  it('uploadCsv should set uploadError on failure', () => {
    mockCourseService.uploadStudentsCsv.mockReturnValue(throwError(() => new Error()));
    component.csvFile = new File([''], 'students.csv');
    component.uploadCsv();
    expect(component.uploadError).toBeTruthy();
    expect(component.isUploading).toBeFalsy();
  });

  it('uploadCsv should do nothing when no file selected', () => {
    component.csvFile = null;
    component.uploadCsv();
    expect(mockCourseService.uploadStudentsCsv).not.toHaveBeenCalled();
  });

  it('clearFile should reset file state', () => {
    component.csvFile = new File([''], 'students.csv');
    component.uploadError = 'some error';
    component.clearFile();
    expect(component.csvFile).toBeNull();
    expect(component.uploadResult).toBeNull();
    expect(component.uploadError).toBe('');
  });

  it('should report how many invitation emails were sent', () => {
    mockCourseService.uploadStudentsCsv.mockReturnValue(
      of({
        enrolled: 2,
        linked: 0,
        pending: 2,
        skipped: 0,
        invited: 2,
        invite_failed: 0,
        warnings: [],
        errors: [],
      }),
    );
    component.selectTab('csv');
    component.csvFile = new File([''], 'students.csv');
    component.uploadCsv();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('2 invitation emails sent');
  });

  it('should surface invitation failures instead of hiding them', () => {
    mockCourseService.uploadStudentsCsv.mockReturnValue(
      of({
        enrolled: 3,
        linked: 0,
        pending: 3,
        skipped: 0,
        invited: 2,
        invite_failed: 1,
        warnings: [],
        errors: [],
      }),
    );
    component.selectTab('csv');
    component.csvFile = new File([''], 'students.csv');
    component.uploadCsv();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent;
    expect(text).toContain('1 invitation email could not be sent');
    expect(text).toContain('were not notified');
  });

  it('should list students already in the class', () => {
    mockCourseService.uploadStudentsCsv.mockReturnValue(
      of({
        enrolled: 1,
        linked: 0,
        pending: 1,
        skipped: 2,
        invited: 0,
        invite_failed: 0,
        warnings: [
          'Row 1: Ada Lovelace (ada@ubco.ca) is already a part of the class.',
          'Row 2: Alan Turing (alan@ubco.ca) is already a part of the class.',
        ],
        errors: [],
      }),
    );
    component.selectTab('csv');
    component.csvFile = new File([''], 'students.csv');
    component.uploadCsv();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Already in the class (2)');
    expect(text).toContain('Ada Lovelace (ada@ubco.ca) is already a part of the class.');
    expect(text).toContain('Alan Turing (alan@ubco.ca) is already a part of the class.');
  });

  it('resendInvites should report how many invitations were sent', () => {
    mockCourseService.resendInvites.mockReturnValue(of({ invited: 2, invite_failed: 1 }));
    component.selectTab('csv');
    component.resendInvites();
    fixture.detectChanges();

    expect(mockCourseService.resendInvites).toHaveBeenCalledWith(component.course.id);
    expect(component.resendResult).toEqual({ invited: 2, invite_failed: 1 });
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('2 invitations sent');
    expect(text).toContain('1 still could not be sent');
  });

  it('resendInvites should surface an error on failure', () => {
    mockCourseService.resendInvites.mockReturnValue(throwError(() => new Error()));
    component.selectTab('csv');
    component.resendInvites();
    fixture.detectChanges();

    expect(component.resendError).toBeTruthy();
    expect(component.isResending).toBeFalsy();
  });
});
