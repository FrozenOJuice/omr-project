import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { WizardSteps } from './wizard-steps';

describe('WizardSteps', () => {
  let component: WizardSteps;
  let fixture: ComponentFixture<WizardSteps>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WizardSteps],
    }).compileComponents();

    fixture = TestBed.createComponent(WizardSteps);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('defaults to step 1 of the create-exam/answer-key/exam-PDFs labels', () => {
    expect(component.current).toBe(1);
    expect(component.labels).toEqual(['Create exam', 'Answer key', 'Exam PDFs']);
  });

  it('renders one step per label with a connector between each', () => {
    fixture.detectChanges();
    const steps = fixture.debugElement.queryAll(By.css('.wizard-step'));
    const connectors = fixture.debugElement.queryAll(By.css('.wizard-step-connector'));
    expect(steps).toHaveLength(3);
    expect(connectors).toHaveLength(2);
  });

  it('marks steps before the current one done and the current one active', () => {
    component.current = 2;
    fixture.detectChanges();

    const circles = fixture.debugElement.queryAll(By.css('.wizard-step-circle'));
    expect(circles[0].classes['done']).toBe(true);
    expect(circles[0].classes['active']).toBeFalsy();
    expect(circles[1].classes['active']).toBe(true);
    expect(circles[1].classes['done']).toBeFalsy();
    expect(circles[2].classes['done']).toBeFalsy();
    expect(circles[2].classes['active']).toBeFalsy();

    const labels = fixture.debugElement.queryAll(By.css('.wizard-step-label'));
    expect(labels[1].classes['active']).toBe(true);
    expect(labels[0].classes['active']).toBeFalsy();
  });

  it('marks the connector done once the step before it is complete', () => {
    component.current = 3;
    fixture.detectChanges();

    const connectors = fixture.debugElement.queryAll(By.css('.wizard-step-connector'));
    expect(connectors[0].classes['done']).toBe(true);
    expect(connectors[1].classes['done']).toBe(true);
  });

  it('renders custom labels when provided', () => {
    component.labels = ['One', 'Two'];
    component.current = 1;
    fixture.detectChanges();

    const labels = fixture.debugElement.queryAll(By.css('.wizard-step-label'))
      .map((el) => el.nativeElement.textContent.trim());
    expect(labels).toEqual(['One', 'Two']);
  });
});
