import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-wizard-steps',
  imports: [],
  templateUrl: './wizard-steps.html',
  styleUrl: './wizard-steps.css',
})
export class WizardSteps {
  @Input() current = 1;
  @Input() labels: string[] = ['Create exam', 'Answer key', 'Exam PDFs'];
}
