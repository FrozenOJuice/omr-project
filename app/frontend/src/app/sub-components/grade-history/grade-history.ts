import { Component, computed, EventEmitter, inject, input, Input, OnInit, Output, signal } from '@angular/core';
import { ExamReleaseAuditEntry, GradeAuditEntry } from '../../models/exam.model';
import { Student, studentFullName } from '../../models/course.model';
import { ExamService } from '../../services/exam.service';

type HistoryEntryKind = 'grade' | 'release';

interface HistoryRow {
  id: string;
  kind: HistoryEntryKind;
  createdAt: string;
  timestamp: string;
  actorLabel: string;
  scoreLabel: string | null;
  summary: string;
}

@Component({
  selector: 'app-grade-history',
  imports: [],
  templateUrl: './grade-history.html',
  styleUrl: './grade-history.css',
})
export class GradeHistory implements OnInit {
  private examService = inject(ExamService);

  @Input() gradeId!: string;
  // The release/unrelease audit log is exam-wide rather than per-grade, but
  // it still affects what a student's grade looked like at any given time,
  // so it's folded into the same timeline instead of a separate popup.
  // Optional: callers that don't know the exam id yet just get grade entries.
  @Input() examId: string | null = null;
  @Input() studentLabel = '';
  // Signal input: courses.ts loads the roster and the grade history in two
  // independent, unordered requests, so the roster can still be empty when
  // history loads. Deriving `rows` via computed() re-renders student names
  // once the roster arrives instead of leaving raw UUIDs baked into a
  // one-shot snapshot taken in ngOnInit.
  roster = input<Student[]>([]);
  @Output() close = new EventEmitter<void>();

  // Signals so the async API response updates the view without relying on
  // zone.js (this app is zoneless) or manual ChangeDetectorRef.markForCheck().
  loading = signal(true);
  error = signal('');
  private gradeEntries = signal<GradeAuditEntry[]>([]);
  private releaseEntries = signal<ExamReleaseAuditEntry[]>([]);

  // Newest first: most recent change is the one staff/students care about.
  rows = computed<HistoryRow[]>(() => {
    const gradeRows = this.gradeEntries().map((entry) => this.toGradeRow(entry));
    const releaseRows = this.releaseEntries().map((entry) => this.toReleaseRow(entry));
    return [...gradeRows, ...releaseRows].sort(
      (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)
    );
  });

  ngOnInit(): void {
    this.examService.getGradeHistory(this.gradeId).subscribe({
      next: (entries) => {
        this.gradeEntries.set(entries);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Unable to load history for this grade.');
        this.loading.set(false);
      },
    });

    // Best-effort: a professor still gets the grade's own history even if
    // this exam-wide fetch fails, so it fails silently rather than blocking
    // the whole popup on a secondary timeline.
    if (this.examId) {
      this.examService.getReleaseHistory(this.examId).subscribe({
        next: (entries) => this.releaseEntries.set(entries),
        error: () => {},
      });
    }
  }

  private toGradeRow(entry: GradeAuditEntry): HistoryRow {
    return {
      id: entry.id,
      kind: 'grade',
      createdAt: entry.created_at,
      timestamp: new Date(entry.created_at).toLocaleString(),
      actorLabel:
        entry.actor_name ??
        (entry.event_type === 'initial_grade' ? 'Automated grading' : 'Course staff'),
      scoreLabel:
        entry.previous_total_score === null
          ? `${entry.new_total_score}`
          : `${entry.previous_total_score} to ${entry.new_total_score}`,
      summary: this.buildSummary(entry),
    };
  }

  private toReleaseRow(entry: ExamReleaseAuditEntry): HistoryRow {
    return {
      id: entry.id,
      kind: 'release',
      createdAt: entry.created_at,
      timestamp: new Date(entry.created_at).toLocaleString(),
      actorLabel: entry.actor_name ?? 'Unknown user',
      scoreLabel: null,
      summary: entry.event_type === 'released' ? 'Released exam results' : 'Unreleased exam results',
    };
  }

  private buildSummary(entry: GradeAuditEntry): string {
    if (entry.event_type === 'initial_grade') return 'Initial automated grade';

    const parts: string[] = [];
    const { changes } = entry;

    if (changes.questions) {
      const questionNumbers = Object.keys(changes.questions).sort((a, b) => Number(a) - Number(b));
      parts.push(`Corrected Q${questionNumbers.join(', Q')}`);
    }
    if (changes.student_id) {
      parts.push(`Reassigned to ${this.studentName(changes.student_id.after)}`);
    }
    if (changes.status && !changes.questions) {
      parts.push('Flag resolved (no answers changed)');
    } else if (changes.status) {
      parts.push('Flag resolved');
    }

    return parts.length > 0 ? parts.join(' · ') : 'Grade updated';
  }

  private studentName(userId: string | null): string {
    if (!userId) return 'Unassigned';
    const student = this.roster().find((s) => s.userId === userId);
    return student ? studentFullName(student) : userId;
  }
}
