import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AdminUserRow } from './admin-user-row';
import { FormsModule } from '@angular/forms';
import { AdminUser } from '../../models/admin.model';

describe('AdminUserRow', () => {
  let component: AdminUserRow;
  let fixture: ComponentFixture<AdminUserRow>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminUserRow, FormsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminUserRow);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('user', new AdminUser(
      '1',
      'Alice',
      'Johnson',
      'alice@ubc.ca',
      'Student',
      'active',
      '2026-06-01T00:00:00Z',
      true,
      '12345678',
    ));
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialise editable fields from the user input', () => {
    expect(component.selectedFirstName).toBe('Alice');
    expect(component.selectedLastName).toBe('Johnson');
    expect(component.selectedEmail).toBe('alice@ubc.ca');
    expect(component.selectedRole).toBe('Student');
    expect(component.selectedStatus).toBe('active');
    expect(component.selectedStudentNumber).toBe('12345678');
  });

  it('should report no changes when fields match the user input', () => {
    expect(component.hasChanges).toBe(false);
  });

  it('should require confirmation before emitting a role change', () => {
    const emitted: Array<{
      userId: string;
      firstName: string;
      lastName: string;
      email: string;
      role: string;
      status: string;
      studentNumber: string | null;
    }> = [];
    component.saveUser.subscribe(e => emitted.push(e));

    component.selectedFirstName = 'Alice';
    component.selectedLastName = 'Updated';
    component.selectedRole = 'Admin';
    component.saveChanges();

    expect(component.pendingAction).toBe('save');
    expect(emitted.length).toBe(0);

    component.confirmPendingAction();

    expect(emitted.length).toBe(1);
    expect(emitted[0]).toEqual({
      userId: '1',
      firstName: 'Alice',
      lastName: 'Updated',
      email: 'alice@ubc.ca',
      role: 'Admin',
      status: 'active',
      studentNumber: null,
    });
  });

  it('should require confirmation before disabling an account', () => {
    component.selectedStatus = 'disabled';

    component.saveChanges();

    expect(component.pendingAction).toBe('save');
  });

  it('should require confirmation before emitting delete', () => {
    const emitted: AdminUser[] = [];
    component.deleteUser.subscribe(user => emitted.push(user));

    component.requestDelete();
    expect(emitted).toEqual([]);

    component.confirmPendingAction();
    expect(emitted).toEqual([component.user]);
  });

  it('should include student number when saving a student row', () => {
    const emitted: Array<{ studentNumber: string | null }> = [];
    component.saveUser.subscribe(e => emitted.push(e));

    component.selectedStudentNumber = '87654321';
    component.saveChanges();

    expect(emitted[0].studentNumber).toBe('87654321');
  });

  it('should report changes when only the student number differs', () => {
    component.selectedStudentNumber = '99999999';
    expect(component.hasChanges).toBe(true);
  });

  it('should allow a student row to be promoted to professor', () => {
    expect(component.roles).toEqual(['Admin', 'Professor', 'Student']);
  });

  it('should exclude Student from the role options for a professor row', () => {
    fixture.componentRef.setInput('user', new AdminUser(
      '2', 'Bob', 'Jones', 'bob@ubc.ca', 'Professor', 'active', '2026-06-01T00:00:00Z', false,
    ));
    fixture.detectChanges();

    expect(component.roles).not.toContain('Student');
    expect(component.roles).toEqual(['Admin', 'Professor']);
  });

  it('should offer all roles for an admin row', () => {
    fixture.componentRef.setInput('user', new AdminUser(
      '3', 'Cara', 'Lee', 'cara@ubc.ca', 'Admin', 'active', '2026-06-01T00:00:00Z', false,
    ));
    fixture.detectChanges();

    expect(component.roles).toEqual(['Admin', 'Professor', 'Student']);
  });

  it('should emit resendSetupEmail with the user', () => {
    const emitted: AdminUser[] = [];
    component.resendSetupEmail.subscribe(u => emitted.push(u));

    component.resendSetupEmail.emit(component.user);

    expect(emitted.length).toBe(1);
    expect(emitted[0].id).toBe('1');
  });
});
