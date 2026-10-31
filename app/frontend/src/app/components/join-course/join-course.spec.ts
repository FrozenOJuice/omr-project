import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { JoinCourse } from './join-course';
import { CourseService } from '../../services/course.service';
import { UserService } from '../../services/user.service';

const MOCK_USER = { id: '1', first_name: 'Alice', last_name: 'Example', email: 'alice@example.com', role: 'student', status: 'active', student_number: '12345678' };

const makeTestBed = (
  inviteLink: string,
  user: typeof MOCK_USER | null,
  joinResult: Observable<unknown>,
) => {
  const mockRouter = { navigate: vi.fn() };
  const mockCourseService = { joinCourse: vi.fn(() => joinResult) };
  const mockUserService = {
    ensureLoaded: vi.fn(() => user ? of(user) : throwError(() => new Error('unauthorized'))),
  };

  TestBed.configureTestingModule({
    imports: [JoinCourse],
    providers: [
      { provide: Router, useValue: mockRouter },
      { provide: CourseService, useValue: mockCourseService },
      { provide: UserService, useValue: mockUserService },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ inviteLink }) } },
      },
    ],
  });

  return { mockRouter, mockCourseService, mockUserService };
};

describe('JoinCourse', () => {
  let fixture: ComponentFixture<JoinCourse>;
  let component: JoinCourse;

  // Initial state (before ngOnInit fires)

  it('should create', () => {
    const { mockRouter } = makeTestBed('abc', MOCK_USER, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    expect(component).toBeTruthy();
  });

  it('should have initial state of "joining"', () => {
    makeTestBed('abc', MOCK_USER, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    expect(component.state).toBe('joining');
  });

  it('should have an empty errorMessage initially', () => {
    makeTestBed('abc', MOCK_USER, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    expect(component.errorMessage).toBe('');
  });

  // No user — redirect to login

  it('should navigate to /login with a returnUrl when no user is logged in', () => {
    const { mockRouter } = makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    fixture.detectChanges();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/login'], {
      queryParams: { returnUrl: '/join/abc' },
    });
  });

  it('should not call joinCourse when no user is logged in', () => {
    const { mockCourseService } = makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    fixture.detectChanges();
    expect(mockCourseService.joinCourse).not.toHaveBeenCalled();
  });

  // Successful join

  it('should call joinCourse with the invite link', () => {
    const inviteLink = 'xyz789';
    const { mockCourseService } = makeTestBed(inviteLink, MOCK_USER, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    fixture.detectChanges();
    expect(mockCourseService.joinCourse).toHaveBeenCalledWith(inviteLink);
  });

  it('should navigate to /courses after a successful join', () => {
    const { mockRouter } = makeTestBed('abc', MOCK_USER, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    fixture.detectChanges();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/courses']);
  });

  // 404 error

  it('should set state to "error" on a 404 response', () => {
    makeTestBed('abc', MOCK_USER, throwError(() => ({ status: 404 })));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.state).toBe('error');
  });

  it('should show the invalid-link message on a 404 response', () => {
    makeTestBed('abc', MOCK_USER, throwError(() => ({ status: 404 })));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.errorMessage).toBe('This invite link is invalid or has expired.');
  });

  // Generic error

  it('should set state to "error" on a non-404 error', () => {
    makeTestBed('abc', MOCK_USER, throwError(() => ({ status: 500 })));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.state).toBe('error');
  });

  it('should show the generic error message on a non-404 error', () => {
    makeTestBed('abc', MOCK_USER, throwError(() => ({ status: 500 })));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.errorMessage).toBe('Something went wrong. Please try again.');
  });

  it('should show the account mismatch message on a 400 response', () => {
    makeTestBed('abc', MOCK_USER, throwError(() => ({ status: 400 })));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.errorMessage).toContain('student number matches');
  });

  // goToCourses

  it('goToCourses() should navigate to /courses', () => {
    const { mockRouter } = makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
    mockRouter.navigate.mockClear();
    component.goToCourses();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/courses']);
  });

  // DOM

  it('should render the spinner in "joining" state', () => {
    makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    component.state = 'joining';
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('.spinner'))).toBeTruthy();
  });

  it('should render the error icon in "error" state', () => {
    makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    component.state = 'error';
    component.errorMessage = 'Something went wrong. Please try again.';
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('.error-icon'))).toBeTruthy();
  });

  it('should render the error message in "error" state', () => {
    makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    component.state = 'error';
    component.errorMessage = 'This invite link is invalid or has expired.';
    fixture.detectChanges();
    const body = fixture.debugElement.query(By.css('.join-body'));
    expect(body.nativeElement.textContent).toContain('This invite link is invalid or has expired.');
  });

  it('should render the Go to Courses button in "error" state', () => {
    makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    component.state = 'error';
    fixture.detectChanges();
    const btn = fixture.debugElement.query(By.css('.action-btn'));
    expect(btn).toBeTruthy();
    expect(btn.nativeElement.textContent).toContain('Go to Courses');
  });

  it('should not render the spinner in "error" state', () => {
    makeTestBed('abc', null, of({ message: 'ok' }));
    fixture = TestBed.createComponent(JoinCourse);
    component = fixture.componentInstance;
    component.state = 'error';
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('.spinner'))).toBeNull();
  });
});
