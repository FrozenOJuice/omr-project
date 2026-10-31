import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { QuestionList } from './question-list';
import { QuestionSnippet } from '../question-snippet/question-snippet';
import { QuestionAnnotation } from '../../models/exam.model';

const mkAnnotation = (overrides: Partial<QuestionAnnotation> = {}): QuestionAnnotation => ({
  question_id: '1',
  bounds: { x: 0, y: 0, width: 200, height: 100 },
  boxes: [],
  confidence: 0.9,
  correct: true,
  ambiguous: false,
  score: 1,
  max_score: 1,
  student_answers: ['A'],
  correct_answers: ['A'],
  ...overrides,
});

describe('QuestionList', () => {
  let component: QuestionList;
  let fixture: ComponentFixture<QuestionList>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [QuestionList],
    }).compileComponents();

    fixture = TestBed.createComponent(QuestionList);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render the question score with an accessible description', () => {
    component.annotations = [mkAnnotation({ score: 3, max_score: 4 })];
    fixture.detectChanges();

    const score = fixture.nativeElement.querySelector('.question-score') as HTMLElement;
    expect(score.textContent?.trim()).toBe('3/4');
    expect(score.getAttribute('aria-label')).toBe('Score 3 out of 4');
  });

  it('should scale the padded bounds (not the raw ones) by a fixed factor so it keeps its aspect ratio', () => {
    // margin = min(100, 50) * 0.3 = 15, padding out to 130x80, then *1.5.
    // Scaling from the padded rect (not the raw one) is what QuestionSnippet
    // actually crops, see padQuestionBounds -- sizing the box from raw
    // bounds would mismatch that and get cover-cropped back down.
    expect(component.snippetSize({ x: 0, y: 0, width: 100, height: 50 })).toEqual({ width: 195, height: 120 });
  });

  it('should render every question at the same height regardless of how many options it has', () => {
    // A true/false row and a many-option row can have wildly different
    // widths in template units, but they share almost the same bubble-row
    // height -- scaling from height (not width) is what keeps them all the
    // same rendered height instead of squashing the wider one flatter.
    const trueFalse = component.snippetSize({ x: 0, y: 0, width: 80, height: 30 });
    const manyOptions = component.snippetSize({ x: 0, y: 0, width: 900, height: 30 });
    expect(trueFalse.height).toBe(manyOptions.height);
    expect(manyOptions.width).toBeGreaterThan(trueFalse.width);
  });

  it('should sync the snippet\'s scroll position proportionally from the answer-options scroll', () => {
    const options = { scrollWidth: 1000, clientWidth: 500, scrollLeft: 250 } as HTMLElement;
    const snippet = { scrollWidth: 400, clientWidth: 200, scrollLeft: 0 } as HTMLElement;

    component.syncSnippetScroll(options, snippet);

    // options is scrolled halfway through its 500px range -- snippet (200px
    // range) should land halfway through its own range too.
    expect(snippet.scrollLeft).toBe(100);
  });

  it('should render answer options from the question\'s own boxes rather than assuming A-E', () => {
    const annotation = mkAnnotation({
      boxes: [
        { label: 'True', selected: false, x: 0, y: 0, width: 20, height: 20 },
        { label: 'False', selected: true, x: 30, y: 0, width: 20, height: 20 },
      ],
      student_answers: ['False'],
      correct_answers: ['False'],
    });
    component.annotations = [annotation];
    fixture.detectChanges();

    component.toggleExpanded('1');
    fixture.detectChanges();

    const labels = Array.from(fixture.nativeElement.querySelectorAll('.answer-btn')).map(
      (el) => (el as HTMLElement).textContent?.trim(),
    );
    expect(labels).toEqual(['True', 'False']);
  });

  it('should not render a snippet while a card is collapsed', () => {
    component.annotations = [mkAnnotation()];
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.directive(QuestionSnippet))).toBeNull();
  });

  it('should render a snippet sized from the row bounds once its card is expanded', () => {
    const annotation = mkAnnotation({ bounds: { x: 10, y: 20, width: 300, height: 150 } });
    component.annotations = [annotation];
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.detectChanges();

    component.toggleExpanded('1');
    fixture.detectChanges();

    const snippet = fixture.debugElement.query(By.directive(QuestionSnippet)).componentInstance as QuestionSnippet;
    expect(snippet.imageUrl()).toBe('blob:page');
    expect(snippet.bounds()).toEqual(annotation.bounds);
    const expected = component.snippetSize(annotation.bounds);
    expect(snippet.boxWidth()).toBe(expected.width);
    expect(snippet.boxHeight()).toBe(expected.height);
  });

  it('should remove the snippet again once the card is collapsed', () => {
    component.annotations = [mkAnnotation()];
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.detectChanges();

    component.toggleExpanded('1');
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.directive(QuestionSnippet))).not.toBeNull();

    component.toggleExpanded('1');
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.directive(QuestionSnippet))).toBeNull();
  });
});
