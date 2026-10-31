import { Component, EventEmitter, Input, Output, computed, effect, input, signal } from '@angular/core';
import { QuestionAnnotation, QuestionBounds } from '../../models/exam.model';
import { padQuestionBounds, QuestionSnippet } from '../question-snippet/question-snippet';

interface QuestionRow {
  questionId: string;
  statusClass: string;
  ambiguous: boolean;
  correct: boolean;
  score: number;
  maxScore: number;
  confidencePercent: number;
  studentAnswers: string[];
  correctAnswers: string[];
  bounds: QuestionBounds;
  // The question's real option set (e.g. ['True', 'False'] vs ['A'..'E']),
  // taken from its own detected boxes rather than assumed, since different
  // questions on the same exam can use different option sets.
  options: string[];
}

@Component({
  selector: 'app-question-list',
  imports: [QuestionSnippet],
  templateUrl: './question-list.html',
  styleUrl: './question-list.css',
})
export class QuestionList {
  @Input() set annotations(value: QuestionAnnotation[]) {
    this._annotations.set(value);
    // A freshly-loaded/refreshed set of annotations means any in-progress
    // edit is either just-saved or stale, so drop it rather than risk
    // showing an answer picker that no longer matches what's on screen.
    this.draftAnswers.set({});
  }
  // The current page's full exam image, so an expanded card can show a
  // cropped preview of its own question.
  imageUrl = input<string | null>(null);
  // Set by the parent when an annotation on the image is clicked, so this
  // list can jump to and open the matching card.
  selectedQuestionId = input<string | null>(null);
  // Students see their own results, not the answer key. Hides the correct
  // answer and the correction editor entirely rather than just disabling them.
  hideAnswerKey = input(false);
  @Output() resolve = new EventEmitter<{ questionId: string; answers: string[] }>();
  // So hovering a card can highlight its annotation on the image, the same
  // way hovering the image already highlights the card's boxes.
  @Output() hover = new EventEmitter<string | null>();

  private _annotations = signal<QuestionAnnotation[]>([]);
  expandedQuestionId = signal<string | null>(null);
  private draftAnswers = signal<Record<string, string[]>>({});

  // Ambiguous questions first (a human hasn't looked at them yet), then in
  // question-number order. A corrected question stops being ambiguous
  // server-side, so it naturally falls back into numeric order next time
  // the parent refreshes annotations, with no manual re-sort needed here.
  rows = computed<QuestionRow[]>(() => {
    const list = this._annotations().map((annotation) => this.toRow(annotation));
    return [...list].sort((a, b) => {
      if (a.ambiguous !== b.ambiguous) return a.ambiguous ? -1 : 1;
      return Number(a.questionId) - Number(b.questionId);
    });
  });

  constructor() {
    effect(() => {
      const id = this.selectedQuestionId();
      if (!id) return;
      this.expandedQuestionId.set(id);
      // Runs after the @if-gated detail panel above has had a chance to
      // render, so the element being scrolled to already has its final size.
      queueMicrotask(() => {
        document.getElementById(`question-card-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

  toggleExpanded(questionId: string): void {
    this.expandedQuestionId.set(this.expandedQuestionId() === questionId ? null : questionId);
  }

  answersFor(row: QuestionRow): string[] {
    return this.draftAnswers()[row.questionId] ?? row.studentAnswers;
  }

  isSelected(row: QuestionRow, option: string): boolean {
    return this.answersFor(row).includes(option);
  }

  toggleAnswer(row: QuestionRow, option: string): void {
    const current = this.answersFor(row);
    const next = current.includes(option) ? current.filter((a) => a !== option) : [...current, option];
    this.draftAnswers.update((drafts) => ({ ...drafts, [row.questionId]: next }));
  }

  save(row: QuestionRow): void {
    this.resolve.emit({ questionId: row.questionId, answers: this.answersFor(row) });
  }

  // A single fixed scale, applied evenly to both axes, so every question's
  // bubbles render at the same true-to-life size. Two questions on the same
  // exam share almost exactly the same bubble-row height in the template's
  // own units and differ only in width (how many options they have) -- so
  // scaling from height (not width) is what makes a true/false row, an A-E
  // row, and a many-option row all come out the SAME rendered height,
  // rather than forcing them all to the same width and crushing the wider
  // ones flatter to fit. A question that ends up wider than its card just
  // scrolls horizontally to see the rest (see .card-snippet-scroll, kept in
  // sync with the answer-options row's own scrollbar) instead of being
  // squashed down to fit.
  private readonly snippetScale = 1.5;

  // Scaled from the PADDED bounds (the same rect QuestionSnippet actually
  // crops, see padQuestionBounds), not the raw ones -- sizing the box from
  // raw bounds would give it a different aspect ratio than what's really
  // being cropped, and QuestionSnippet's cover-fit crop would silently chop
  // the padding (or real content) back off to force-fit that mismatch.
  snippetSize(bounds: QuestionBounds): { width: number; height: number } {
    const padded = padQuestionBounds(bounds);
    return { width: padded.width * this.snippetScale, height: padded.height * this.snippetScale };
  }

  // The answer-options row is the one visible/interactive horizontal
  // scrollbar; the snippet has no scrollbar of its own (see
  // .card-snippet-scroll's overflow: hidden) and instead just follows the
  // options row's scroll position, proportionally, so scrolling to see a
  // later option is one action instead of two separate scrollbars to drag.
  syncSnippetScroll(optionsEl: HTMLElement, snippetEl: HTMLElement): void {
    const optionsRange = optionsEl.scrollWidth - optionsEl.clientWidth;
    const snippetRange = snippetEl.scrollWidth - snippetEl.clientWidth;
    snippetEl.scrollLeft = optionsRange > 0 ? (optionsEl.scrollLeft / optionsRange) * snippetRange : 0;
  }

  private toRow(annotation: QuestionAnnotation): QuestionRow {
    const statusClass = annotation.ambiguous
      ? 'status-ambiguous'
      : annotation.correct
        ? 'status-correct'
        : 'status-incorrect';
    return {
      questionId: annotation.question_id,
      statusClass,
      ambiguous: annotation.ambiguous,
      correct: annotation.correct,
      score: annotation.score,
      maxScore: annotation.max_score,
      confidencePercent: Math.round(annotation.confidence * 100),
      studentAnswers: annotation.student_answers,
      correctAnswers: annotation.correct_answers,
      bounds: annotation.bounds,
      // One box per template option, in template order, regardless of what
      // was marked -- see OptionBox: it's always the full option set for
      // this specific question, not just what got selected.
      options: annotation.boxes.map((box) => box.label),
    };
  }
}
