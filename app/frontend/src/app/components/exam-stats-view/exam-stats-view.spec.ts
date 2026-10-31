import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { vi } from 'vitest';
import { ApiExam, ExamStats } from '../../models/exam.model';
import { ExamService } from '../../services/exam.service';
import { ExamStatsView } from './exam-stats-view';

const MOCK_EXAM = {
  id: 'exam-1',
  name: 'Midterm',
  course_id: 'course-1',
} as ApiExam;

const question = {
  question_number: '1',
  graded_count: 4,
  correct_count: 2,
  correct_percentage: 50,
  incorrect_count: 2,
  incorrect_percentage: 50,
  average_score: 0.5,
  max_score: 1,
  selected_distribution: { A: 2, B: 2 },
  answer_choices: [
    {
      answer: 'A',
      selected_count: 2,
      selected_percentage: 50,
      is_correct: true,
      high_group_percentage: 100,
      low_group_percentage: 0,
      effectiveness: 'correct' as const,
    },
    {
      answer: 'B',
      selected_count: 2,
      selected_percentage: 50,
      is_correct: false,
      high_group_percentage: 0,
      low_group_percentage: 100,
      effectiveness: 'effective' as const,
    },
  ],
  item_difficulty: 0.5,
  discrimination_index: 0.4,
  distractor_efficiency: 1,
};

const MOCK_STATS: ExamStats = {
  exam_id: 'exam-1',
  graded_count: 6,
  mean_score: 7.5,
  standard_deviation_score: 1.2,
  median_score: 8,
  mode_scores: [8],
  highest_score: 10,
  lowest_score: 4,
  mean_percentage: 75,
  standard_deviation_percentage: 12,
  min_percentage: 40,
  q1_percentage: 62.5,
  median_percentage: 75,
  q3_percentage: 80,
  max_percentage: 90,
  score_distribution: [0, 0, 0, 0, 1, 0, 1, 1, 2, 1].map((count, index) => ({
    label: `${index * 10}-${index === 9 ? 100 : index * 10 + 9}%`,
    lower_bound: index * 10,
    upper_bound: index === 9 ? 100 : index * 10 + 9,
    count,
    percentage: Math.round((count / 6) * 10000) / 100,
  })),
  question_stats: [question],
  version_stats: [
    {
      exam_version: 'A',
      graded_count: 4,
      mean_percentage: 80,
      average_item_difficulty: 0.5,
      average_discrimination_index: 0.4,
      average_distractor_efficiency: 1,
      difficult_question_count: 0,
      low_discrimination_question_count: 0,
      weak_distractor_question_count: 0,
      question_stats: [question],
    },
    {
      exam_version: 'B',
      graded_count: 2,
      mean_percentage: 60,
      average_item_difficulty: 0.25,
      average_discrimination_index: 0.1,
      average_distractor_efficiency: 0.33,
      difficult_question_count: 1,
      low_discrimination_question_count: 1,
      weak_distractor_question_count: 1,
      question_stats: [
        {
          ...question,
          correct_count: 1,
          correct_percentage: 25,
          incorrect_count: 3,
          incorrect_percentage: 75,
        },
      ],
    },
  ],
};

describe('ExamStatsView', () => {
  let fixture: ComponentFixture<ExamStatsView>;
  let component: ExamStatsView;

  const examService = {
    getExam: vi.fn(() => of(MOCK_EXAM)),
    getExamStats: vi.fn(() => of(MOCK_STATS)),
  };
  const router = {
    navigate: vi.fn(),
    getCurrentNavigation: vi.fn(() => null),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    await TestBed.configureTestingModule({
      imports: [ExamStatsView],
      providers: [
        { provide: ExamService, useValue: examService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: { get: (key: string) => (key === 'examId' ? 'exam-1' : null) },
              queryParamMap: { get: (key: string) => (key === 'gradeId' ? 'grade-1' : null) },
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ExamStatsView);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('loads the exam-wide analysis in a large dialog without a page title', () => {
    expect(examService.getExam).toHaveBeenCalledWith('exam-1');
    expect(examService.getExamStats).toHaveBeenCalledWith('exam-1');
    expect(fixture.nativeElement.querySelector('.stats-overlay')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.exam-stats-dialog')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('h1')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Midterm');
    expect(fixture.nativeElement.textContent).toContain('75%');
  });

  it('renders an interactive overview graph and toggles its display mode', () => {
    expect(fixture.debugElement.query(By.css('.distribution-line'))).not.toBeNull();
    expect(fixture.debugElement.queryAll(By.css('.distribution-point'))).toHaveLength(10);
    expect(
      fixture.debugElement.query(By.css('.distribution-point .app-tooltip__content')),
    ).not.toBeNull();

    fixture.debugElement.queryAll(By.css('.segmented-control button'))[1].nativeElement.click();
    fixture.detectChanges();

    expect(component.overviewGraphMode).toBe('bar');
    expect(fixture.debugElement.queryAll(By.css('.distribution-bar'))).toHaveLength(10);
  });

  it('shows the five-number summary in the single overview metrics row', () => {
    const metrics = fixture.debugElement.queryAll(By.css('.stats-grid .stat-tile'));

    expect(metrics).toHaveLength(9);
    expect(fixture.nativeElement.textContent).toContain('First quartile');
    expect(fixture.nativeElement.textContent).toContain('62.5%');
    expect(fixture.nativeElement.textContent).toContain('Third quartile');
    expect(fixture.nativeElement.textContent).toContain('90%');
  });

  it('renders asynchronously loaded statistics without another user interaction', async () => {
    fixture.destroy();
    const statsSubject = new Subject<ExamStats>();
    examService.getExamStats.mockReturnValueOnce(statsSubject);
    const asyncFixture = TestBed.createComponent(ExamStatsView);
    asyncFixture.detectChanges();
    expect(asyncFixture.nativeElement.textContent).toContain('Loading statistics');

    statsSubject.next(MOCK_STATS);
    await asyncFixture.whenStable();

    expect(asyncFixture.nativeElement.textContent).toContain('75%');
    expect(asyncFixture.nativeElement.textContent).not.toContain('Loading statistics');
    asyncFixture.destroy();
  });

  it('shows per-version answer percentages and the three analysis indices', () => {
    const tabs = fixture.debugElement.queryAll(By.css('.tab-btn'));
    expect(tabs).toHaveLength(2);
    tabs[1].nativeElement.click();
    fixture.detectChanges();

    const questionRow = fixture.debugElement.query(By.css('.question-analysis-row'));
    expect(questionRow.query(By.css('.question-details'))).toBeNull();
    questionRow.query(By.css('.question-toggle')).nativeElement.click();
    fixture.detectChanges();

    expect(questionRow.nativeElement.textContent).toContain('50% correct');
    expect(questionRow.nativeElement.textContent).toContain('2/4 correct');
    expect(questionRow.nativeElement.textContent).not.toContain('wrong');
    const optionRows = questionRow.queryAll(By.css('.option-row'));
    expect(optionRows).toHaveLength(2);
    expect(optionRows[0].nativeElement.textContent).toContain('2');
    expect(optionRows[0].nativeElement.textContent).toContain('50%');
    expect(questionRow.nativeElement.textContent).toContain('Item difficulty');
    expect(questionRow.nativeElement.textContent).toContain('Discrimination');
    expect(questionRow.nativeElement.textContent).toContain('Distractor efficiency');
    expect(questionRow.queryAll(By.css('.app-tooltip__content'))).toHaveLength(3);

    fixture.debugElement.queryAll(By.css('.version-btn'))[1].nativeElement.click();
    fixture.detectChanges();
    const versionBQuestion = fixture.debugElement.query(By.css('.question-analysis-row'));
    expect(fixture.nativeElement.textContent).toContain('25% correct');
    expect(versionBQuestion.query(By.css('.question-percent--danger'))).not.toBeNull();
    expect(versionBQuestion.nativeElement.textContent).toContain('Very difficult');
  });

  it('expands and collapses all question cards', () => {
    fixture.debugElement.queryAll(By.css('.tab-btn'))[1].nativeElement.click();
    fixture.detectChanges();

    const controls = fixture.debugElement.queryAll(By.css('.section-toolbar .action-btn'));
    controls[0].nativeElement.click();
    fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.css('.question-details'))).toHaveLength(1);

    controls[1].nativeElement.click();
    fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.css('.question-details'))).toHaveLength(0);
  });

  it('includes version quality comparisons below the overview metrics', () => {
    const cards = fixture.debugElement.queryAll(By.css('.version-comparison-card'));
    expect(cards).toHaveLength(2);
    expect(cards[0].queryAll(By.css('.metric-help'))).toHaveLength(3);
    expect(cards[0].queryAll(By.css('.app-tooltip__content'))).toHaveLength(3);
    expect(cards[1].nativeElement.textContent).toContain('Version B');
    expect(cards[1].nativeElement.textContent).toContain('Fairness flags');
    expect(cards[1].nativeElement.textContent).toContain('Weak distractors');
    expect(fixture.nativeElement.textContent).not.toContain('lowest average item difficulty');
    expect(
      fixture.debugElement.query(By.css('.version-insights .material-icons-outlined')),
    ).toBeNull();
  });

  it('returns to the exact grade results page', () => {
    component.goBack();
    expect(router.navigate).toHaveBeenCalledWith(['/grades', 'grade-1', 'annotations']);
  });
});
