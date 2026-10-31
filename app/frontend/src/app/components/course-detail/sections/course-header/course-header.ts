import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Course, courseBadgeFromCode, formatAcademicPeriod } from '../../../../models/course.model';

@Component({
  selector: 'app-course-header',
  templateUrl: './course-header.html',
  styleUrl: './course-header.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CourseHeader {
  readonly course = input.required<Course>();
  readonly canManage = input(false);
  readonly showBack = input(true);
  readonly isRestoring = input(false);
  readonly back = output<void>();
  readonly edit = output<void>();
  readonly remove = output<void>();
  readonly restore = output<void>();

  readonly formatAcademicPeriod = formatAcademicPeriod;
  readonly courseBadgeFromCode = courseBadgeFromCode;

  readonly hasHistory = computed(() => this.course().exams.length > 0 || this.course().students > 0);
}
