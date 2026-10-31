import { Component, ElementRef, EventEmitter, HostListener, OnDestroy, Output, ViewChild, computed, effect, input, signal } from '@angular/core';
import { IdentityAnnotations, IdentityFieldAnnotation, OptionBox, VersionAnnotation } from '../../models/exam.model';
import { padQuestionBounds, QuestionSnippet } from '../question-snippet/question-snippet';

export interface PositionedBox {
  key: string;
  questionId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  statusClass: string;
}

// A generous hover/click hit-region covering a whole question rather than
// each small bubble, so hovering anywhere near it (not just precisely on a
// bubble) works. Purely a hit-target; visual feedback comes from the boxes
// and, while hovering, the snippet preview below. `title` is only set for
// the identity/version groups, which don't get a snippet preview of their
// own and so still rely on a plain native tooltip.
export interface PositionedRegion {
  questionId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  title?: string;
}

// Renders one exam scan page with its annotation boxes overlaid, shared by
// the professor (annotated-exam-view) and student (student-exam-view) exam
// pages: the positioning math and page navigation are identical for both,
// only which boxes/regions get passed in (and what surrounds this) differs.
@Component({
  selector: 'app-exam-page-viewer',
  imports: [QuestionSnippet],
  templateUrl: './exam-page-viewer.html',
  styleUrl: './exam-page-viewer.css',
})
export class ExamPageViewer implements OnDestroy {
  page = input(0);
  pageCount = input(1);
  loading = input(false);
  error = input('');
  imageUrl = input<string | null>(null);
  regions = input<PositionedRegion[]>([]);
  boxes = input<PositionedBox[]>([]);
  // Name/student-ID bubble fields on this page, if any, and the
  // version-selector bubble if this template has one and it's on this page.
  // Converted to boxes/regions internally (see identityBoxes etc. below) so
  // that positioning math isn't duplicated by every caller.
  identity = input<IdentityAnnotations | null>(null);
  version = input<VersionAnnotation | null>(null);
  hoveredQuestionId = input<string | null>(null);
  // Question ids to permanently outline (not just on hover), in the same
  // amber used for an ambiguous answer -- e.g. regrade-requests marking
  // which question(s) a request is actually about, distinct from any
  // correct/incorrect coloring on the bubbles themselves.
  highlightedQuestionIds = input<string[]>([]);
  // Identifies which scan is being previewed (e.g. the exam grade id), as
  // distinct from page: page navigation within a scan changes imageUrl too,
  // but shouldn't reset zoom, whereas switching to a different scan should.
  gradeId = input<string | null>(null);
  // Opt-in: bounds the page image to a fixed-height, independently
  // scrollable viewport with its own zoom controls, instead of the image
  // dictating the whole component's height. Off by default so the
  // full-page results views (which want the scan at its natural size) are
  // unaffected; the regrade-requests preview, which sits in a fixed-size
  // pane next to other content, turns it on.
  zoomable = input(false);

  @Output() prevPage = new EventEmitter<void>();
  @Output() nextPage = new EventEmitter<void>();
  @Output() hover = new EventEmitter<string | null>();
  @Output() select = new EventEmitter<string>();

  @ViewChild('pageImage') private pageImageRef?: ElementRef<HTMLImageElement>;
  @ViewChild('imageWrapper') private imageWrapperRef?: ElementRef<HTMLDivElement>;

  // The image's own natural pixel size. Annotation boxes are in those same
  // scan-pixel coordinates, so positioning them as percentages of this size
  // keeps them aligned at whatever size the image is actually rendered.
  private naturalWidth = signal(1);
  private naturalHeight = signal(1);

  // Not reset on page change: browsing pages while zoomed in shouldn't
  // require re-zooming on every page.
  zoomLevel = signal(1);
  zoomPercent = computed(() => Math.round(this.zoomLevel() * 100));

  // Click-drag panning within the bounded zoomed viewport. Tracked with
  // plain window listeners (always registered, no-ops via the early return
  // below) rather than setPointerCapture: capturing on the wrapper would
  // retarget the up/click events that land on a bubble's question-region,
  // breaking click-to-select whenever a drag happened to end on one.
  private panState: { startX: number; startY: number; scrollLeft: number; scrollTop: number } | null = null;

  // Which region the pointer is currently over the image for, and where the
  // pointer is, driving the floating "zoomed in" snippet preview below.
  // Separate from hoveredQuestionId, since that one is also driven by
  // hovering a question-list card, where there's no cursor position over
  // the image to anchor a preview to.
  previewRegion = signal<PositionedRegion | null>(null);
  private cursor = signal<{ x: number; y: number } | null>(null);
  // A short delay before the preview appears, so quickly sweeping the
  // cursor across the page doesn't pop up a snippet for every question
  // passed over, only one the user actually paused on.
  private readonly previewDelayMs = 250;
  private previewTimer: ReturnType<typeof setTimeout> | null = null;

  // The same fixed scale as question-list's manual-review snippet, applied
  // evenly to both axes, so a hovered question reads at the same true-to-
  // life size regardless of how many options it has. Unlike that snippet,
  // this tooltip has no scrollbar to reveal anything cropped out of it, so
  // it can't cap width/height independently (that doesn't preserve aspect
  // ratio, and chops off the sides of a wide question instead of just
  // rendering it more zoomed out). Instead, the one shared scale is capped
  // against the actual viewport (with room for the cursor offset and edge
  // margin) rather than an arbitrary small box -- realistic content still
  // renders at the normal scale, and only a question wide enough to not
  // fit the screen at that scale shrinks, uniformly, never cropped.
  private readonly previewScale = 1.5;

  previewSize = computed<{ width: number; height: number } | null>(() => {
    const region = this.previewRegion();
    if (!region) return null;
    // Scaled from the PADDED region (the same rect QuestionSnippet actually
    // crops, see padQuestionBounds), not the raw one -- sizing the box from
    // raw bounds would give it a different aspect ratio than what's really
    // being cropped, and QuestionSnippet's cover-fit crop would silently
    // chop the padding (or real content) back off to force-fit that
    // mismatch.
    const padded = padQuestionBounds(region);
    const maxWidth = window.innerWidth - 64;
    const maxHeight = window.innerHeight - 64;
    const scale = Math.min(this.previewScale, maxWidth / padded.width, maxHeight / padded.height);
    return { width: padded.width * scale, height: padded.height * scale };
  });

  // Offset from the cursor so the preview doesn't sit directly over (and
  // hide) the annotation being hovered, flipping to whichever side of the
  // cursor still fits on screen near a viewport edge.
  previewPositionStyle = computed<Record<string, string> | null>(() => {
    const size = this.previewSize();
    const cursor = this.cursor();
    if (!size || !cursor) return null;

    const margin = 12;
    const offset = 20;
    let left = cursor.x + offset;
    let top = cursor.y + offset;
    if (left + size.width + margin > window.innerWidth) left = cursor.x - offset - size.width;
    if (top + size.height + margin > window.innerHeight) top = cursor.y - offset - size.height;
    left = Math.min(Math.max(margin, left), window.innerWidth - size.width - margin);
    top = Math.min(Math.max(margin, top), window.innerHeight - size.height - margin);

    return { left: `${left}px`, top: `${top}px` };
  });

  constructor() {
    // Switching to a different scan (a new regrade request selected, say)
    // should start fresh even though the component instance is reused.
    effect(() => {
      this.gradeId();
      this.resetZoom();
    });
  }

  onPanStart(event: PointerEvent): void {
    if (!this.zoomable() || event.button !== 0) return;
    const wrapper = this.imageWrapperRef?.nativeElement;
    if (!wrapper) return;
    this.panState = {
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: wrapper.scrollLeft,
      scrollTop: wrapper.scrollTop,
    };
  }

  @HostListener('window:pointermove', ['$event'])
  onWindowPointerMove(event: PointerEvent): void {
    const state = this.panState;
    const wrapper = this.imageWrapperRef?.nativeElement;
    if (!state || !wrapper) return;
    // If the button was released outside the viewport, no pointerup ever
    // reaches us. event.buttons reflects the live button state on every
    // move, so this catches that case and ends the drag.
    if (event.buttons === 0) {
      this.panState = null;
      return;
    }
    wrapper.scrollLeft = state.scrollLeft - (event.clientX - state.startX);
    wrapper.scrollTop = state.scrollTop - (event.clientY - state.startY);
  }

  @HostListener('window:pointerup')
  onWindowPointerUp(): void {
    this.panState = null;
  }

  identityBoxes = computed<PositionedBox[]>(() => {
    const identity = this.identity();
    if (!identity) return [];
    // Only the marked bubble: there's no correct/incorrect here, so the
    // other ~25 empty options in each column would just be visual noise.
    return identity.fields.flatMap((field) =>
      field.boxes
        .filter((box) => box.selected)
        .map((box) => this.toPositionedBox(field, box, this.identityGroupId(field.field_type))),
    );
  });

  // Grouped hover regions matching the identity card's "Detected name"
  // (first + last combined) and "Detected ID" rows, so hovering either
  // highlights every bubble in that group together.
  identityRegions = computed<PositionedRegion[]>(() => {
    const identity = this.identity();
    if (!identity) return [];
    const name = identity.fields.filter((f) => f.field_type !== 'student_id');
    const id = identity.fields.filter((f) => f.field_type === 'student_id');
    return [this.toGroupRegion('identity-name', name), this.toGroupRegion('identity-id', id)].filter(
      (region): region is PositionedRegion => region !== null,
    );
  });

  versionBox = computed<PositionedBox | null>(() => {
    const field = this.version()?.field;
    const box = field?.boxes.find((b) => b.selected);
    return field && box ? this.toPositionedBox(field, box, 'identity-version') : null;
  });

  versionRegion = computed<PositionedRegion | null>(() => {
    const field = this.version()?.field;
    return field ? this.toGroupRegion('identity-version', [field]) : null;
  });

  highlightRegions = computed<PositionedRegion[]>(() => {
    const ids = this.highlightedQuestionIds();
    if (ids.length === 0) return [];
    return this.regions().filter((region) => ids.includes(region.questionId));
  });

  get isFirstPage(): boolean {
    return this.page() === 0;
  }

  get isLastPage(): boolean {
    return this.page() >= this.pageCount() - 1;
  }

  zoomIn(): void {
    this.zoomLevel.set(Math.min(2, Math.round((this.zoomLevel() + 0.25) * 100) / 100));
  }

  zoomOut(): void {
    this.zoomLevel.set(Math.max(0.5, Math.round((this.zoomLevel() - 0.25) * 100) / 100));
  }

  resetZoom(): void {
    this.zoomLevel.set(1);
    const wrapper = this.imageWrapperRef?.nativeElement;
    if (wrapper) {
      wrapper.scrollLeft = 0;
      wrapper.scrollTop = 0;
    }
  }

  onImageLoad(): void {
    const img = this.pageImageRef?.nativeElement;
    if (!img?.naturalWidth || !img.naturalHeight) return;
    this.naturalWidth.set(img.naturalWidth);
    this.naturalHeight.set(img.naturalHeight);
  }

  // A flagged question's outline uses the same hit-region bounds as
  // question-region (see PositionedRegion's doc comment), which sit right
  // up against the bubbles themselves -- fine for an invisible click
  // target, but too tight for a visible border, which would cut through
  // the bubbles it's meant to surround. Padding is proportional to the
  // region's own height (roughly one bubble's diameter) so it scales
  // sensibly regardless of the scan's actual pixel resolution.
  private static readonly HIGHLIGHT_PADDING_RATIO = 0.4;

  highlightRectStyle(region: PositionedRegion): Record<string, string> {
    const pad = region.height * ExamPageViewer.HIGHLIGHT_PADDING_RATIO;
    return this.rectStyle({
      x: region.x - pad,
      y: region.y - pad,
      width: region.width + pad * 2,
      height: region.height + pad * 2,
    });
  }

  onRegionEnter(region: PositionedRegion, event: MouseEvent): void {
    this.hover.emit(region.questionId);
    this.cursor.set({ x: event.clientX, y: event.clientY });
    this.clearPreviewTimer();
    this.previewTimer = setTimeout(() => this.previewRegion.set(region), this.previewDelayMs);
  }

  onRegionLeave(): void {
    this.hover.emit(null);
    this.clearPreviewTimer();
    this.previewRegion.set(null);
  }

  onPointerMove(event: MouseEvent): void {
    if (this.previewRegion() || this.previewTimer) this.cursor.set({ x: event.clientX, y: event.clientY });
  }

  ngOnDestroy(): void {
    this.clearPreviewTimer();
  }

  private clearPreviewTimer(): void {
    if (this.previewTimer === null) return;
    clearTimeout(this.previewTimer);
    this.previewTimer = null;
  }

  rectStyle(rect: { x: number; y: number; width: number; height: number }): Record<string, string> {
    const width = this.naturalWidth();
    const height = this.naturalHeight();
    return {
      left: `${(rect.x / width) * 100}%`,
      top: `${(rect.y / height) * 100}%`,
      width: `${(rect.width / width) * 100}%`,
      height: `${(rect.height / height) * 100}%`,
    };
  }

  private identityGroupId(fieldType: string): string {
    return fieldType === 'student_id' ? 'identity-id' : 'identity-name';
  }

  private toPositionedBox(
    field: { field_type: string; field_index: number },
    box: OptionBox,
    groupId: string,
  ): PositionedBox {
    return {
      key: `${field.field_type}-${field.field_index}-${box.label}`,
      questionId: groupId,
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      statusClass: 'status-identity',
    };
  }

  private toGroupRegion(groupId: string, fields: IdentityFieldAnnotation[]): PositionedRegion | null {
    const bounds = this.unionBounds(fields);
    return bounds ? { questionId: groupId, ...bounds, title: 'Detected' } : null;
  }

  private unionBounds(
    fields: { bounds: { x: number; y: number; width: number; height: number } }[],
  ): { x: number; y: number; width: number; height: number } | null {
    if (!fields.length) return null;
    const minX = Math.min(...fields.map((f) => f.bounds.x));
    const minY = Math.min(...fields.map((f) => f.bounds.y));
    const maxX = Math.max(...fields.map((f) => f.bounds.x + f.bounds.width));
    const maxY = Math.max(...fields.map((f) => f.bounds.y + f.bounds.height));
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
  }
}
