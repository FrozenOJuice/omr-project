import { Component, inject, Input } from '@angular/core';
import { DatePipe, NgClass } from '@angular/common';
import { ApiReviewRequest } from '../../models/regrade-requests.model';
import { RegradeStatusClass, RegradeStatusLabel } from '../../enums/tags.enum';
import { Router } from '@angular/router';

@Component({
  selector: 'app-dashboard-regrade-requests-card',
  imports: [NgClass, DatePipe],
  templateUrl: './dashboard-regrade-requests-card.html',
  styleUrl: './dashboard-regrade-requests-card.css',
})
export class DashboardRegradeRequestsCard {
  @Input() request!: ApiReviewRequest;

  readonly RegradeStatusClass = RegradeStatusClass;
  readonly RegradeStatusLabel = RegradeStatusLabel;

  private router = inject(Router);

  redirectToRequest() {
    this.router.navigate(['/regrade'])
  }
}
