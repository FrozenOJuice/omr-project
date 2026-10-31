import { Component, EventEmitter, Output, computed, input } from '@angular/core';
import { IdentityAnnotations } from '../../models/exam.model';

// The "Identify Student" card shared by the professor (annotated-exam-view)
// and student (student-exam-view) exam pages: the detected name/ID display
// and click-to-jump-to-page behavior are identical for both. Anything
// beyond that (the professor's reassign-student flow, flag badges) is
// role-specific and left to the parent via content projection, rather than
// threading roster/assign state through this component's inputs.
@Component({
  selector: 'app-identity-card',
  imports: [],
  templateUrl: './identity-card.html',
  styleUrl: './identity-card.css',
})
export class IdentityCard {
  // Not page-scoped: fetched once by the parent so this card stays visible
  // on every page and knows which page to jump to.
  gradeIdentity = input<IdentityAnnotations | null>(null);
  isOnIdentityPage = input(false);
  hoveredQuestionId = input<string | null>(null);

  @Output() goToPage = new EventEmitter<void>();
  @Output() hover = new EventEmitter<string | null>();

  // The weakest character in a field determines how much to trust the whole
  // decoded string, so this is a min, not an average.
  nameConfidence = computed(() => this.fieldConfidencePercent(['last_name', 'first_name']));
  idConfidence = computed(() => this.fieldConfidencePercent(['student_id']));

  private fieldConfidencePercent(fieldTypes: string[]): number | null {
    const fields = this.gradeIdentity()?.fields.filter((f) => fieldTypes.includes(f.field_type)) ?? [];
    if (!fields.length) return null;
    return Math.round(Math.min(...fields.map((f) => f.confidence)) * 100);
  }
}
