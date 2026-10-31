import { Component, input } from '@angular/core';

// The score-tile row shared by the professor (annotated-exam-view) and
// student (student-exam-view) exam pages. classMeanPercent/percentDiff are
// staff-only (the class-stats endpoint students can't call), so that tile
// simply never renders when they're left null.
@Component({
  selector: 'app-score-summary',
  imports: [],
  templateUrl: './score-summary.html',
  styleUrl: './score-summary.css',
})
export class ScoreSummary {
  percentage = input<number | null>(null);
  totalScore = input<number | null>(null);
  maxScore = input<number | null>(null);
  classMeanPercent = input<number | null>(null);
  percentDiff = input<number | null>(null);
}
