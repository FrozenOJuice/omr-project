import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Registration } from './registration';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';

describe('Registration', () => {
  let component: Registration;
  let fixture: ComponentFixture<Registration>;
  const mockRouter = {
    navigate: vi.fn(),
    navigateByUrl: vi.fn(),
  };
  const mockAuthService = {
    register: vi.fn(() => of({ access_token: 'access', refresh_token: 'refresh', token_type: 'bearer' })),
  };
  const mockRoute = {
    snapshot: {
      queryParamMap: {
        get: vi.fn(() => null),
      },
    },
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockAuthService.register.mockReturnValue(of({ access_token: 'access', refresh_token: 'refresh', token_type: 'bearer' }));

    await TestBed.configureTestingModule({
      imports: [Registration, FormsModule],
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: AuthService, useValue: mockAuthService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Registration);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should show Create Account form title', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    const formTitle = fixture.nativeElement.querySelector('#formTitle');
    expect(formTitle.textContent).toContain('Create Account');
  });

  it('should set errorMessage if create account is submitted with empty fields', () => {
    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Please fill in all fields.');
  });

  it('should set errorMessage if passwords do not match on create account', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.confirmPassword = 'different';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Passwords do not match.');
  });

  it('should set errorMessage if password does not meet requirements', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'weakpass';
    component.confirmPassword = 'weakpass';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Password must be at least 12 characters and contain an uppercase letter, lowercase letter, number, and special character.');
  });

  it('should not set errorMessage when create account fields are valid', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.confirmPassword = 'Password123!';
    component.studentNumber = '12345678';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('');
  });

  it('should set errorMessage if student role is submitted without a student number', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.confirmPassword = 'Password123!';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Student number must be exactly 8 digits.');
  });

  it('should set errorMessage if student number is not 8 digits', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.confirmPassword = 'Password123!';
    component.studentNumber = '123';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Student number must be exactly 8 digits.');
  });

  it('should not require a student number for professor accounts', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.confirmPassword = 'Password123!';
    component.role = 'professor';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('');
  });

  it('should set errorMessage if email does not meet requirements', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'testexample.com';
    component.password = 'Secure@1';
    component.confirmPassword = 'Secure@1';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('Please enter a valid email address.');
  });

  it('should not set errorMessage when email meets all requirements', () => {
    component.firstName = 'Test';
    component.lastName = 'User';
    component.email = 'test@example.com';
    component.password = 'Secure@1';
    component.confirmPassword = 'Secure@1';
    component.studentNumber = '12345678';

    const mockEvent = new MouseEvent('click');
    component.createAccount(mockEvent);
    expect(component.errorMessage()).toBe('');
  });

  it('should clear errorMessage when clearError is called', () => {
    component.errorMessage.set('Some error');
    component.clearError();
    expect(component.errorMessage()).toBe('');
  });
});
