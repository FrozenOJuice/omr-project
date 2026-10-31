import { Component, EventEmitter, Input, Output, computed, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ExamGrade } from '../../models/exam.model';
import { Student, studentFullName } from '../../models/course.model';

export interface RosterSelection {
  gradeId: string;
  name: string;
}

interface RosterRow {
  gradeId: string;
  name: string;
  studentNumber: string | null;
  percent: number | null;
  needsReview: boolean;
}

@Component({
  selector: 'app-grade-roster',
  imports: [FormsModule],
  templateUrl: './grade-roster.html',
  styleUrl: './grade-roster.css',
})
export class GradeRoster {
  @Input() set grades(value: ExamGrade[]) {
    this._grades.set(value);
  }
  @Input() set roster(value: Student[]) {
    this._roster.set(value);
  }
  currentGradeId = input<string | null>(null);
  @Output() selectGrade = new EventEmitter<RosterSelection>();

  search = signal('');

  private _grades = signal<ExamGrade[]>([]);
  private _roster = signal<Student[]>([]);

  // Anyone needing attention first (a grade-level flag or a per-question
  // ambiguous mark), then alphabetical so the rest is easy to scan.
  rows = computed<RosterRow[]>(() => {
    const roster = this._roster();
    const query = this.search().trim().toLowerCase();
    const mapped = this._grades().map((grade) => this.toRow(grade, roster));
    const filtered = query
      ? mapped.filter(
          (row) =>
            row.name.toLowerCase().includes(query) || (row.studentNumber ?? '').toLowerCase().includes(query),
        )
      : mapped;
    return [...filtered].sort((a, b) => {
      if (a.needsReview !== b.needsReview) return a.needsReview ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  });

  onSelect(row: RosterRow): void {
    this.selectGrade.emit({ gradeId: row.gradeId, name: row.name });
  }

  private toRow(grade: ExamGrade, roster: Student[]): RosterRow {
    const student = roster.find((s) => s.userId === grade.student_id);
    const name = !grade.student_id ? 'Unmatched' : student ? studentFullName(student) : grade.student_id;
    const needsReview =
      grade.status === 'needs_review' || Object.values(grade.question_results).some((result) => result.ambiguous);
    return {
      gradeId: grade.id,
      name,
      studentNumber: student?.studentNumber ?? null,
      percent: grade.max_score ? Math.round((grade.total_score / grade.max_score) * 1000) / 10 : null,
      needsReview,
    };
  }
}
