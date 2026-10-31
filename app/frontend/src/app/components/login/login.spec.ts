import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Login } from './login';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';

describe('Login', () => {
  let component: Login;
  let fixture: ComponentFixture<Login>;
  const mockRouter = {
    navigate: vi.fn(),
    navigateByUrl: vi.fn(),
  };
  const mockAuthService = {
    login: vi.fn(() => of({ access_token: 'access', refresh_token: 'refresh', token_type: 'bearer' })),
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
    mockAuthService.login.mockReturnValue(of({ access_token: 'access', refresh_token: 'refresh', token_type: 'bearer' }));

    await TestBed.configureTestingModule({
      imports: [Login, FormsModule],
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockRoute },
        { provide: AuthService, useValue: mockAuthService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Login);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should show Sign In form title', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    const formTitle = fixture.nativeElement.querySelector('#formTitle');
    expect(formTitle.textContent).toContain('Welcome back');
  });

  it('should set errorMessage if sign in is submitted with empty fields', () => {
    const mockEvent = new MouseEvent('click');
    component.signIn(mockEvent);
    expect(component.errorMessage()).toBe('Please fill in all fields.');
  });

  it('should set errorMessage if email is invalid on sign in', () => {
    component.email = 'notanemail';
    component.password = 'somepassword';

    const mockEvent = new MouseEvent('click');
    component.signIn(mockEvent);
    expect(component.errorMessage()).toBe('Please enter a valid email address.');
  });

  it('should not set errorMessage when sign in fields are valid', () => {
    component.email = 'test@example.com';
    component.password = 'Password123!';

    const mockEvent = new MouseEvent('click');
    component.signIn(mockEvent);
    expect(component.errorMessage()).toBe('');
  });

  it('should clear errorMessage when clearError is called', () => {
    component.errorMessage.set('Some error');
    component.clearError();
    expect(component.errorMessage()).toBe('');
  });

  // Remember me

  it('should default rememberMe to false', () => {
    expect(component.rememberMe).toBe(false);
  });

  it('should pass rememberMe=false to authService.login by default', () => {
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.signIn(new MouseEvent('click'));
    expect(mockAuthService.login).toHaveBeenCalledWith('test@example.com', 'Password123!', false);
  });

  it('should pass rememberMe=true to authService.login when the checkbox is checked', () => {
    component.email = 'test@example.com';
    component.password = 'Password123!';
    component.rememberMe = true;
    component.signIn(new MouseEvent('click'));
    expect(mockAuthService.login).toHaveBeenCalledWith('test@example.com', 'Password123!', true);
  });

  it('should bind the remember-me checkbox to the rememberMe field', async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    const checkbox: HTMLInputElement = fixture.nativeElement.querySelector('#remember');
    expect(checkbox.checked).toBe(false);

    checkbox.click();
    checkbox.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.rememberMe).toBe(true);
  });
});
