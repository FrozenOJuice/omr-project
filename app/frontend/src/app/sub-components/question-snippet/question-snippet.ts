import { Component, ElementRef, ViewChild, computed, input, signal } from '@angular/core';
import { QuestionBounds } from '../../models/exam.model';

// Grows a bounds rect outward on every side, so a snippet shows some of the
// surrounding page rather than butting right up against the outermost
// bubbles. One margin shared by both axes keeps the padding visually even
// on all four sides instead of ballooning on whichever axis bounds is
// longer on -- based on the SHORTER dimension specifically (not an average
// of both), since a question's bounds can be much wider than it is tall
// (many options in a row) without being any taller, and averaging in that
// extra width used to inflate the margin enough to pull in neighboring page
// content, like the question's own printed number sitting just left of the
// bubble row.
//
// Exported so callers sizing a box for QuestionSnippet (question-list,
// exam-page-viewer) can size it from THIS padded rect's aspect ratio rather
// than the raw bounds' -- otherwise the box doesn't match what actually
// gets cropped below (paddedBounds), and QuestionSnippet's cover-fit crop
// silently chops the mismatched margin (or worse, real bubble content) back
// off to force-fit the box, defeating the point of padding it at all.
export const SNIPPET_MARGIN_RATIO = 0.3;

export function padQuestionBounds(bounds: QuestionBounds): QuestionBounds {
  const margin = Math.min(bounds.width, bounds.height) * SNIPPET_MARGIN_RATIO;
  return {
    x: bounds.x - margin,
    y: bounds.y - margin,
    width: bounds.width + margin * 2,
    height: bounds.height + margin * 2,
  };
}

// Crops a region out of an already-loaded exam page image by overscaling an
// <img> inside a fixed, overflow-hidden box and offsetting it so `bounds`
// lines up with the box, reusing the same percentage-of-natural-size math
// exam-page-viewer already uses for its annotation boxes instead of a canvas
// redraw or a server-cropped image. Shared by the question card snippet
// (question-list) and the hover preview (exam-page-viewer); they only differ
// in what box size they pass in.
@Component({
  selector: 'app-question-snippet',
  imports: [],
  templateUrl: './question-snippet.html',
  styleUrl: './question-snippet.css',
})
export class QuestionSnippet {
  imageUrl = input<string | null>(null);
  bounds = input<QuestionBounds | null>(null);
  boxWidth = input(96);
  boxHeight = input(64);

  @ViewChild('sourceImage') private sourceImageRef?: ElementRef<HTMLImageElement>;

  private naturalWidth = signal(0);
  private naturalHeight = signal(0);

  private paddedBounds = computed<QuestionBounds | null>(() => {
    const bounds = this.bounds();
    return bounds ? padQuestionBounds(bounds) : null;
  });

  hostStyle = computed<Record<string, string>>(() => ({
    width: `${this.boxWidth()}px`,
    height: `${this.boxHeight()}px`,
  }));

  // Scaled up (never down) so the padded bounds always fills the box,
  // clipping a little off whichever edge doesn't match the box's aspect
  // ratio, same as a CSS object-fit: cover thumbnail.
  imageStyle = computed<Record<string, string>>(() => {
    const bounds = this.paddedBounds();
    const nw = this.naturalWidth();
    const nh = this.naturalHeight();
    const bw = this.boxWidth();
    const bh = this.boxHeight();
    if (!bounds || !nw || !nh || !bounds.width || !bounds.height) {
      return { visibility: 'hidden', width: '0', height: '0', left: '0', top: '0' };
    }

    const scale = Math.max(bw / bounds.width, bh / bounds.height);
    const croppedWidth = bounds.width * scale;
    const croppedHeight = bounds.height * scale;

    return {
      visibility: 'visible',
      width: `${nw * scale}px`,
      height: `${nh * scale}px`,
      left: `${-(bounds.x * scale) - (croppedWidth - bw) / 2}px`,
      top: `${-(bounds.y * scale) - (croppedHeight - bh) / 2}px`,
    };
  });

  onImageLoad(): void {
    const img = this.sourceImageRef?.nativeElement;
    if (!img?.naturalWidth || !img.naturalHeight) return;
    this.naturalWidth.set(img.naturalWidth);
    this.naturalHeight.set(img.naturalHeight);
  }
}
