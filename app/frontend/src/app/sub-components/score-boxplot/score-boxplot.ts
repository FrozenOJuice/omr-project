import { Component, computed, input, signal } from '@angular/core';

export interface FiveNumberSummary {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

type SummaryKey = keyof FiveNumberSummary;

const VIEW_WIDTH = 220;
const VIEW_HEIGHT = 46;
const PLOT_LEFT = 18;
const PLOT_RIGHT = 202;
const PLOT_Y = 20;
const BOX_HALF_HEIGHT = 7;
// Taller than the highlight dot's own visual radius (see .boxplot-highlight
// in the stylesheet), so a cap still pokes out on both ends when a
// highlighted score sits exactly at the min or max, instead of the dot's
// halo fully covering it.
const CAP_HALF_HEIGHT = 8;

// A compact horizontal box plot of a class's exam scores (as percentages),
// with the currently-viewed student's own score marked against it. One
// series is the point, the rest is context, so the distribution reads as
// de-emphasized gray and only the highlighted score carries the accent
// color. Horizontal and small on purpose: it shares a narrow sidebar
// column with other cards and shouldn't compete with the exam page image
// for space.
@Component({
  selector: 'app-score-boxplot',
  imports: [],
  templateUrl: './score-boxplot.html',
  styleUrl: './score-boxplot.css',
})
export class ScoreBoxplot {
  // Every grade's percentage for the exam. Used when the caller has the raw
  // list to compute a summary from client-side (the professor view, which
  // already loads every grade for the roster panel).
  scores = input<number[]>([]);
  // A summary already computed elsewhere (e.g. server-side, for the student
  // view, which only ever gets the aggregate, never other students' raw
  // scores). Takes priority over `scores` when set.
  precomputedSummary = input<FiveNumberSummary | null>(null);
  // How many scores the summary was computed from. Only needed alongside
  // precomputedSummary; with `scores`, the count is just its length.
  precomputedCount = input<number | null>(null);
  // The currently-viewed student's percentage, marked distinctly from the
  // rest of the distribution. Null hides the marker (e.g. an unmatched grade).
  highlightScore = input<number | null>(null);
  highlightLabel = input('This student');
  activeSummaryKey = signal<SummaryKey | null>(null);

  readonly viewBox = `0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`;
  readonly axisTicks = [0, 25, 50, 75, 100];
  readonly plotY = PLOT_Y;
  readonly boxHalfHeight = BOX_HALF_HEIGHT;
  readonly capHalfHeight = CAP_HALF_HEIGHT;
  readonly axisLabelY = PLOT_Y + 16;

  studentCount = computed(() => this.precomputedCount() ?? this.scores().length);

  summary = computed<FiveNumberSummary | null>(() => {
    const precomputed = this.precomputedSummary();
    if (precomputed) return precomputed;

    const sorted = [...this.scores()].sort((a, b) => a - b);
    if (sorted.length === 0) return null;
    return {
      min: sorted[0],
      q1: this.quantile(sorted, 0.25),
      median: this.quantile(sorted, 0.5),
      q3: this.quantile(sorted, 0.75),
      max: sorted[sorted.length - 1],
    };
  });

  boxLeft = computed(() => this.xFor(this.summary()?.q1 ?? 0));
  boxRight = computed(() => this.xFor(this.summary()?.q3 ?? 0));
  boxWidth = computed(() => this.boxRight() - this.boxLeft());
  medianX = computed(() => this.xFor(this.summary()?.median ?? 0));
  minX = computed(() => this.xFor(this.summary()?.min ?? 0));
  maxX = computed(() => this.xFor(this.summary()?.max ?? 0));
  highlightX = computed(() => {
    const score = this.highlightScore();
    return score != null ? this.xFor(score) : null;
  });
  summaryItems = computed(() => {
    const summary = this.summary();
    if (!summary) return [];
    return [
      { key: 'min' as const, label: 'Min', value: summary.min },
      { key: 'q1' as const, label: 'Q1', value: summary.q1 },
      { key: 'median' as const, label: 'Median', value: summary.median },
      { key: 'q3' as const, label: 'Q3', value: summary.q3 },
      { key: 'max' as const, label: 'Max', value: summary.max },
    ];
  });

  ariaLabel = computed(() => {
    const s = this.summary();
    if (!s) return 'No scores to plot.';
    const parts = [
      `Box plot of exam scores. Minimum ${s.min}%`,
      `first quartile ${s.q1}%`,
      `median ${s.median}%`,
      `third quartile ${s.q3}%`,
      `maximum ${s.max}%`,
    ];
    const highlight = this.highlightScore();
    if (highlight != null) parts.push(`${this.highlightLabel()} at ${highlight}%`);
    return parts.join(', ') + '.';
  });

  xFor(percent: number): number {
    return PLOT_LEFT + (percent / 100) * (PLOT_RIGHT - PLOT_LEFT);
  }

  setActiveSummary(key: SummaryKey | null): void {
    this.activeSummaryKey.set(key);
  }

  // Keeps the 0%/100% tick labels from overflowing the viewBox at the
  // plot's edges, where a centered anchor would clip half the text.
  tickAnchor(tick: number): 'start' | 'middle' | 'end' {
    if (tick === 0) return 'start';
    if (tick === 100) return 'end';
    return 'middle';
  }

  private quantile(sorted: number[], q: number): number {
    const pos = (sorted.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    const value = sorted[base + 1] !== undefined
      ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
      : sorted[base];
    return Math.round(value * 10) / 10;
  }
}
