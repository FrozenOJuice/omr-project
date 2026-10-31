import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { StudentList } from './student-list';
import { Course, Student } from '../../models/course.model';
import { CourseService } from '../../services/course.service';
import { CanvasService } from '../../services/canvas.service';
import { NotificationService } from '../../services/notification.service';

const makeStudent = (id: string, firstName: string, lastName: string, studentNumber: string): Student => ({
  id,
  userId: `user-${id}`,
  firstName,
  lastName,
  email: `${id}@example.com`,
  studentNumber,
  accountStatus: 'linked',
  source: 'manual',
  active: true,
});

const mockStudents: Student[] = [
  makeStudent('1', 'Alice', 'Johnson', '12345678'),
  makeStudent('2', 'Emma', 'Davis', '56789012'),
  makeStudent('3', 'Carol', 'White', '34567890'),
  makeStudent('4', 'Bob', 'Smith', '23456789'),
  makeStudent('5', 'David', 'Lee', '45678901'),
];

const mockCourse: Course = {
  id: 'course-1',
  code: 'COSC 499',
  name: 'Capstone',
  students: 5,
  academicTerm: {
    id: 'summer-1', institution: 'ubc', code: 'summer-session-1',
    name: 'Summer Session 1', term_type: 'preset', year_format: 'following_year',
    is_active: true, created_by: null, created_at: '', updated_at: '',
  },
  academicYearStart: 2026,
  archivedAt: null,
  source: 'omr',
  canvasLink: null,
  canManageCanvas: false,
  exams: [],
  studentList: mockStudents,
  inviteLink: 'link-1',
};

describe('StudentList', () => {
  let component: StudentList;
  let fixture: ComponentFixture<StudentList>;
  const mockCourseService = {
    unenrollStudent: vi.fn(() => of(undefined)),
    promoteStudent: vi.fn(() => of(undefined)),
  };
  const mockCanvasService = {
    syncRoster: vi.fn(),
    inviteStudent: vi.fn(),
    invitePendingStudents: vi.fn(),
  };
  const mockNotifications = { showToast: vi.fn() };

  beforeEach(async () => {
    mockCourseService.unenrollStudent.mockReturnValue(of(undefined));
    mockCourseService.promoteStudent.mockReturnValue(of(undefined));

    await TestBed.configureTestingModule({
      imports: [StudentList],
      providers: [
        { provide: CourseService, useValue: mockCourseService },
        { provide: CanvasService, useValue: mockCanvasService },
        { provide: NotificationService, useValue: mockNotifications },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(StudentList);
    component = fixture.componentInstance;
    component.course = { ...mockCourse, studentList: [...mockStudents] };
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('does not allow Canvas-managed students to be removed manually', () => {
    const managed = { ...mockStudents[0], source: 'canvas' as const };
    component.course = { ...component.course, source: 'canvas', studentList: [managed] };
    component.requestRemoveStudent(managed);
    fixture.detectChanges();

    expect(component.pendingRemoval).toBeNull();
    expect(fixture.nativeElement.querySelector('[title="Managed by Canvas roster sync"]')).not.toBeNull();
  });

  it('distinguishes sent and unsent pending invitations', () => {
    component.course = { ...component.course, source: 'canvas' };
    const pending = { ...mockStudents[0], accountStatus: 'pending' as const, userId: null };
    expect(component.accountStatusLabel(pending)).toBe('Not invited');
    expect(component.accountStatusLabel({ ...pending, invitedAt: '2026-07-19T12:00:00Z' }))
      .toBe('Invitation sent');
  });

  it('shows students removed from the Canvas roster without inviting them', () => {
    const removed = {
      ...mockStudents[0],
      source: 'canvas' as const,
      active: false,
      accountStatus: 'pending' as const,
      userId: null,
      invitedAt: null,
    };
    component.course = {
      ...component.course,
      source: 'canvas',
      canManageCanvas: true,
      studentList: [removed],
    };
    fixture.detectChanges();

    expect(component.accountStatusLabel(removed)).toBe('Removed from Canvas');
    expect(component.pendingInvitationCount).toBe(0);
    expect(fixture.nativeElement.querySelector('.status-badge.tag-outline')?.textContent.trim())
      .toBe('Removed from Canvas');
    expect(fixture.nativeElement.querySelector('.invite-btn')).toBeNull();
  });

  it('synchronizes a Canvas roster from the Students section', () => {
    component.course = {
      ...component.course,
      source: 'canvas',
      canManageCanvas: true,
    };
    const result = {
      added: 1, updated: 0, removed: 0, skipped: 0, active: 6,
      skip_reasons: {},
      last_synced_at: '2026-07-19T12:00:00Z',
    };
    mockCanvasService.syncRoster.mockReturnValue(of(result));
    const changed = vi.spyOn(component.rosterChanged, 'emit');

    component.syncRoster();

    expect(mockCanvasService.syncRoster).toHaveBeenCalledWith('course-1');
    expect(mockNotifications.showToast).toHaveBeenCalledWith(
      'Canvas roster synced', '1 added, 0 updated, 0 removed.',
    );
    expect(changed).toHaveBeenCalledWith(result);
  });

  it('invites one pending Canvas student', () => {
    const pending = {
      ...mockStudents[0], userId: null, accountStatus: 'pending' as const, invitedAt: null,
    };
    component.course = {
      ...component.course,
      source: 'canvas',
      canManageCanvas: true,
      studentList: [pending],
    };
    mockCanvasService.inviteStudent.mockReturnValue(of({
      sent: 1, already_invited: 0, linked: 0, failed: 0, pending: 0,
    }));
    const changed = vi.spyOn(component.rosterChanged, 'emit');

    component.inviteStudent(pending);

    expect(mockCanvasService.inviteStudent).toHaveBeenCalledWith('course-1', pending.id);
    expect(mockNotifications.showToast).toHaveBeenCalledWith(
      'Canvas invitation sent', 'Invitation sent to Alice Johnson.',
    );
    expect(changed).toHaveBeenCalledWith(null);
  });

  it('confirms before inviting all pending Canvas students', () => {
    const pending = {
      ...mockStudents[0], userId: null, accountStatus: 'pending' as const, invitedAt: null,
    };
    component.course = {
      ...component.course,
      source: 'canvas',
      canManageCanvas: true,
      studentList: [pending],
    };
    mockCanvasService.invitePendingStudents.mockReturnValue(of({
      sent: 1, already_invited: 0, linked: 0, failed: 0, pending: 0,
    }));

    component.requestInviteAll();
    expect(component.confirmingInviteAll).toBe(true);
    component.inviteAll();

    expect(mockCanvasService.invitePendingStudents).toHaveBeenCalledWith('course-1');
    expect(component.confirmingInviteAll).toBe(false);
    expect(mockNotifications.showToast).toHaveBeenCalledWith(
      'Canvas invitations sent', '1 invitation sent.', 'info',
    );
  });

  it('hides Canvas roster actions from a non-owner administrator', () => {
    component.course = {
      ...component.course,
      source: 'canvas',
      canManageCanvas: false,
    };
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.canvas-roster-tools')).toBeNull();
  });

  // filteredStudents - filtering

  it('returns all students when searchQuery is empty', () => {
    component.searchQuery = '';
    expect(component.filteredStudents.length).toBe(5);
  });

  it('filters by partial name (case-insensitive)', () => {
    component.searchQuery = 'alice';
    const result = component.filteredStudents;
    expect(result.length).toBe(1);
    expect(component.fullName(result[0])).toBe('Alice Johnson');
  });

  it('filters by uppercase name query', () => {
    component.searchQuery = 'EMMA';
    const result = component.filteredStudents;
    expect(result.length).toBe(1);
    expect(component.fullName(result[0])).toBe('Emma Davis');
  });

  it('filters by partial student number', () => {
    component.searchQuery = '1234';
    const result = component.filteredStudents;
    expect(result.every(s => (s.studentNumber ?? '').includes('1234'))).toBe(true);
  });

  it('returns empty array when no students match', () => {
    component.searchQuery = 'ZZZZZZZZ';
    expect(component.filteredStudents.length).toBe(0);
  });

  it('matches both name and student number within the same search', () => {
    // '4567' matches Alice (12345678) and Carol (34567890) and David (45678901)
    component.searchQuery = '4567';
    expect(component.filteredStudents.length).toBeGreaterThan(0);
    component.filteredStudents.forEach(s => {
      expect(
        (s.studentNumber ?? '').includes('4567') || component.fullName(s).toLowerCase().includes('4567')
      ).toBe(true);
    });
  });

  // default sort state

  it('defaults sortField to name', () => {
    expect(component.sortField).toBe('name');
  });

  it('defaults sortDir to asc', () => {
    expect(component.sortDir).toBe('asc');
  });

  it('returns students sorted by name ascending by default', () => {
    const names = component.filteredStudents.map(s => component.fullName(s));
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });

  // setSort

  it('toggles direction to desc when same field is clicked', () => {
    component.sortField = 'name';
    component.sortDir = 'asc';
    component.setSort('name');
    expect(component.sortDir).toBe('desc');
  });

  it('toggles direction back to asc when clicked again', () => {
    component.sortField = 'name';
    component.sortDir = 'desc';
    component.setSort('name');
    expect(component.sortDir).toBe('asc');
  });

  it('switches field and resets direction to asc', () => {
    component.sortField = 'name';
    component.sortDir = 'desc';
    component.setSort('studentNumber');
    expect(component.sortField).toBe('studentNumber');
    expect(component.sortDir).toBe('asc');
  });

  it('does not change direction when switching to a new field', () => {
    component.sortField = 'name';
    component.sortDir = 'asc';
    component.setSort('studentNumber');
    expect(component.sortDir).toBe('asc');
  });

  // filteredStudents - sorting

  it('sorts by name descending after toggle', () => {
    component.sortField = 'name';
    component.sortDir = 'desc';
    const names = component.filteredStudents.map(s => component.fullName(s));
    expect(names).toEqual([...names].sort((a, b) => b.localeCompare(a)));
  });

  it('sorts by student number ascending', () => {
    component.sortField = 'studentNumber';
    component.sortDir = 'asc';
    const ids = component.filteredStudents.map(s => s.studentNumber);
    expect(ids).toEqual([...ids].sort((a, b) => (a ?? '').localeCompare(b ?? '')));
  });

  it('sorts by student number descending', () => {
    component.sortField = 'studentNumber';
    component.sortDir = 'desc';
    const ids = component.filteredStudents.map(s => s.studentNumber);
    expect(ids).toEqual([...ids].sort((a, b) => (b ?? '').localeCompare(a ?? '')));
  });

  it('applies sort after filtering', () => {
    component.searchQuery = 'a';
    component.sortField = 'name';
    component.sortDir = 'asc';
    const names = component.filteredStudents.map(s => component.fullName(s));
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });

  it('requests confirmation before removing a student', () => {
    component.requestRemoveStudent(mockStudents[0]);
    expect(component.pendingRemoval).toEqual(mockStudents[0]);
    expect(component.removeError).toBe('');
  });

  it('cancels a pending student removal', () => {
    component.requestRemoveStudent(mockStudents[0]);
    component.cancelRemoveStudent();
    expect(component.pendingRemoval).toBeNull();
  });

  it('unenrolls a student and lets the parent update the roster after confirmation', () => {
    const emitSpy = vi.spyOn(component.studentRemoved, 'emit');
    component.requestRemoveStudent(mockStudents[0]);

    component.confirmRemoveStudent();

    expect(mockCourseService.unenrollStudent).toHaveBeenCalledWith('course-1', '1');
    expect(component.course.studentList.map(s => s.id)).toEqual(['1', '2', '3', '4', '5']);
    expect(component.course.students).toBe(5);
    expect(emitSpy).toHaveBeenCalledWith(mockStudents[0]);
    expect(component.pendingRemoval).toBeNull();
    expect(component.removingStudentId).toBeNull();
  });

  it('shows an error and keeps the student when unenroll fails', () => {
    mockCourseService.unenrollStudent.mockReturnValueOnce(throwError(() => new Error('nope')));
    component.requestRemoveStudent(mockStudents[0]);

    component.confirmRemoveStudent();

    expect(component.course.studentList.length).toBe(5);
    expect(component.removeError).toBe('Unable to remove this student. Please try again.');
    expect(component.pendingRemoval).toEqual(mockStudents[0]);
    expect(component.removingStudentId).toBeNull();
  });

  // promote to professor

  it('only allows promoting a linked, active, non-Canvas student when isOwner is set', () => {
    component.isOwner = true;
    expect(component.canPromote(mockStudents[0])).toBe(true);
    expect(component.canPromote({ ...mockStudents[0], accountStatus: 'pending' })).toBe(false);
    expect(component.canPromote({ ...mockStudents[0], active: false })).toBe(false);
    expect(component.canPromote({ ...mockStudents[0], source: 'canvas' })).toBe(false);
  });

  it('does not allow promoting when the current user is not the course owner', () => {
    component.isOwner = false;
    expect(component.canPromote(mockStudents[0])).toBe(false);
  });

  it('requests confirmation before promoting a student', () => {
    component.isOwner = true;
    component.requestPromoteStudent(mockStudents[0]);
    expect(component.pendingPromotion).toEqual(mockStudents[0]);
    expect(component.promoteError).toBe('');
  });

  it('ignores a promotion request when the student is not promotable', () => {
    component.isOwner = false;
    component.requestPromoteStudent(mockStudents[0]);
    expect(component.pendingPromotion).toBeNull();
  });

  it('cancels a pending promotion', () => {
    component.isOwner = true;
    component.requestPromoteStudent(mockStudents[0]);
    component.cancelPromoteStudent();
    expect(component.pendingPromotion).toBeNull();
  });

  it('promotes a student and lets the parent update the roster after confirmation', () => {
    component.isOwner = true;
    const emitSpy = vi.spyOn(component.studentPromoted, 'emit');
    component.requestPromoteStudent(mockStudents[0]);

    component.confirmPromoteStudent();

    expect(mockCourseService.promoteStudent).toHaveBeenCalledWith('course-1', '1');
    expect(emitSpy).toHaveBeenCalledWith(mockStudents[0]);
    expect(component.pendingPromotion).toBeNull();
    expect(component.promotingStudentId).toBeNull();
  });

  it('shows an error and keeps the student when promotion fails', () => {
    component.isOwner = true;
    mockCourseService.promoteStudent.mockReturnValueOnce(throwError(() => new Error('nope')));
    component.requestPromoteStudent(mockStudents[0]);

    component.confirmPromoteStudent();

    expect(component.promoteError).toBe('Unable to promote this student. Please try again.');
    expect(component.pendingPromotion).toEqual(mockStudents[0]);
    expect(component.promotingStudentId).toBeNull();
  });
});
