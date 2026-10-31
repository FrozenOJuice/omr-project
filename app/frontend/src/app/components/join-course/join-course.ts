import { ChangeDetectorRef, Component, inject, OnInit } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { CourseService } from '../../services/course.service';
import { UserService } from '../../services/user.service';

type JoinState = 'joining' | 'error';

@Component({
  selector: 'app-join-course',
  imports: [],
  templateUrl: './join-course.html',
  styleUrl: './join-course.css',
})
export class JoinCourse implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private courseService = inject(CourseService);
  private userService = inject(UserService);
  private cdr = inject(ChangeDetectorRef);

  state: JoinState = 'joining';
  errorMessage = '';

  ngOnInit(): void {
    const inviteLink = this.route.snapshot.paramMap.get('inviteLink') ?? '';
    this.userService.ensureLoaded().subscribe({
      next: () => {
        this.courseService.joinCourse(inviteLink).subscribe({
          next: () => this.router.navigate(['/courses']),
          error: (err) => {
            this.state = 'error';
            if (err.status === 404) {
              this.errorMessage = 'This invite link is invalid or has expired.';
            } else if (err.status === 400) {
              this.errorMessage = 'This invite could not be applied to your account. Please check that your student number matches the course roster.';
            } else {
              this.errorMessage = 'Something went wrong. Please try again.';
            }
            this.cdr.markForCheck();
          },
        });
      },
      error: () => {
        this.router.navigate(['/login'], {
          queryParams: { returnUrl: `/join/${inviteLink}` },
        });
      },
    });
  }

  goToCourses(): void {
    this.router.navigate(['/courses']);
  }
}
