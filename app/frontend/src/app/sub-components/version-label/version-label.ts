import { Component, EventEmitter, Output, computed, input } from '@angular/core';
import { VersionAnnotation } from '../../models/exam.model';

// The "Version X" badge in the page header, shared by the professor
// (annotated-exam-view) and student (student-exam-view) exam pages. Renders
// nothing if this template has no version-selector bubble, or it hasn't
// been decoded yet.
@Component({
  selector: 'app-version-label',
  imports: [],
  templateUrl: './version-label.html',
  styleUrl: './version-label.css',
})
export class VersionLabel {
  version = input<VersionAnnotation | null>(null);
  hovered = input(false);

  @Output() hover = new EventEmitter<string | null>();

  confidencePercent = computed(() => {
    const confidence = this.version()?.field?.confidence;
    return confidence != null ? Math.round(confidence * 100) : null;
  });
}
