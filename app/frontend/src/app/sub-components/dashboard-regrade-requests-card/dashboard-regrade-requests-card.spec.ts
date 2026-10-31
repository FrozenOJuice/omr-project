import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { DashboardRegradeRequestsCard } from './dashboard-regrade-requests-card';
import { ApiReviewRequest } from '../../models/regrade-requests.model';
import { RegradeStatus } from '../../enums/tags.enum';

const mkRequest = (overrides: Partial<ApiReviewRequest>): ApiReviewRequest => ({
  id: 'r1',
  exam_grade_id: 'g1',
  student_id: 's1',
  batch_id: null,
  question_number: '4',
  student_comment: 'Question 4 marking rubric was applied inconsistently.',
  status: RegradeStatus.Pending,
  instructor_response: null,
  current_score: 72,
  proposed_score: 85,
  proposed_correct: null,
  created_at: '2026-06-08',
  resolved_at: null,
  student_name: 'Alice Johnson',
  course_id: 'course-1',
  course_code: 'COSC 304',
  term: 'WS1',
  exam_name: 'Midterm Exam',
  max_score: 100,
  ...overrides,
});

const mockRequest = mkRequest({});

describe('DashboardRegradeRequestsCard', () => {
  let component: DashboardRegradeRequestsCard;
  let fixture: ComponentFixture<DashboardRegradeRequestsCard>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DashboardRegradeRequestsCard],
    }).compileComponents();

    fixture = TestBed.createComponent(DashboardRegradeRequestsCard);
    component = fixture.componentInstance;
    component.request = mockRequest;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display the student name', () => {
    const el = fixture.debugElement.query(By.css('.regrade-student'));
    expect(el.nativeElement.textContent.trim()).toBe('Alice Johnson');
  });

  it('should display the exam name', () => {
    const el = fixture.debugElement.query(By.css('.regrade-meta'));
    expect(el.nativeElement.textContent.trim()).toBe('Midterm Exam');
  });

  it('should display the reason', () => {
    const el = fixture.debugElement.query(By.css('.regrade-reason'));
    expect(el.nativeElement.textContent.trim()).toBe('Question 4 marking rubric was applied inconsistently.');
  });

  it('should display a formatted request date', () => {
    const el = fixture.debugElement.query(By.css('.regrade-date'));
    expect(el.nativeElement.textContent.trim()).toBe('Jun 8, 2026');
  });

  it('should display the status badge', () => {
    const el = fixture.debugElement.query(By.css('.status-badge'));
    expect(el.nativeElement.textContent.trim()).toBe('Pending');
  });

  it('should apply the correct status CSS class', () => {
    const el = fixture.debugElement.query(By.css('.status-badge'));
    expect(el.nativeElement.classList.contains('tag-blue')).toBe(true);
  });

  it('should apply tag-teal class for Resolved requests', () => {
    fixture.componentRef.setInput('request', mkRequest({ status: RegradeStatus.Resolved }));
    fixture.detectChanges();
    const el = fixture.debugElement.query(By.css('.status-badge'));
    expect(el.nativeElement.classList.contains('tag-teal')).toBe(true);
  });

  it('should apply tag-red class for Rejected requests', () => {
    fixture.componentRef.setInput('request', mkRequest({ status: RegradeStatus.Rejected }));
    fixture.detectChanges();
    const el = fixture.debugElement.query(By.css('.status-badge'));
    expect(el.nativeElement.classList.contains('tag-red')).toBe(true);
  });

  it('should render a view button', () => {
    const btn = fixture.debugElement.query(By.css('.view-btn'));
    expect(btn).toBeTruthy();
  });
});
