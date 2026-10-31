import { Component } from '@angular/core';

// The two/three-column shell shared by the professor (annotated-exam-view)
// and student (student-exam-view) exam pages: an optional roster switcher,
// the page viewer, and a fixed-width sidebar. Content projection rather
// than inputs, since what actually goes in each slot (score summary,
// identity card, question list, review-request form, roster) differs
// enough per role that passing it all through inputs would just move the
// duplication here instead of removing it.
@Component({
  selector: 'app-exam-result-layout',
  imports: [],
  templateUrl: './exam-result-layout.html',
  styleUrl: './exam-result-layout.css',
})
export class ExamResultLayout {}
