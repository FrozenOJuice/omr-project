import { ChangeDetectorRef, Component, Input, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CanvasConnection } from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';
import { extractApiErrorMessage } from '../../utils/api-error';

@Component({
  selector: 'app-canvas-account',
  imports: [FormsModule],
  templateUrl: './canvas-account.html',
  styleUrl: './canvas-account.css',
})
export class CanvasAccount implements OnInit {
  private canvasService = inject(CanvasService);
  private cdr = inject(ChangeDetectorRef);

  @Input() settingsUrl: string | null = null;

  connection: CanvasConnection | null = null;
  loading = false;
  actionPending = false;
  replacingToken = false;
  accessToken = '';
  error = '';
  notice = '';

  ngOnInit(): void {
    this.loadConnection();
  }

  connect(): void {
    const accessToken = this.accessToken.trim();
    if (!accessToken) {
      this.error = 'Enter a Canvas access token.';
      return;
    }

    const replacing = this.connection?.connected === true;
    this.actionPending = true;
    this.error = '';
    this.notice = '';
    this.canvasService.connect(accessToken).subscribe({
      next: (connection) => {
        this.connection = connection;
        this.finishTokenRequest();
        this.notice = replacing
          ? 'Canvas access token replaced.'
          : 'Canvas connected successfully.';
      },
      error: (error) => {
        this.finishTokenRequest(!replacing);
        this.failAction(error, 'Canvas could not be connected. Check the token and try again.');
      },
    });
  }

  replaceToken(): void {
    this.replacingToken = true;
    this.accessToken = '';
    this.error = '';
    this.notice = '';
  }

  cancelReplacement(): void {
    this.replacingToken = false;
    this.accessToken = '';
    this.error = '';
  }

  disconnect(): void {
    this.actionPending = true;
    this.error = '';
    this.canvasService.disconnect().subscribe({
      next: () => {
        this.connection = {
          connected: false,
          user_name: null,
          login_id: null,
          connected_at: null,
          last_verified_at: null,
        };
        this.accessToken = '';
        this.replacingToken = false;
        this.actionPending = false;
        this.notice =
          'Canvas disconnected from OMR. Revoke the token in Canvas if you no longer need it.';
        this.cdr.markForCheck();
      },
      error: (error) => this.failAction(error, 'Canvas could not be disconnected.'),
    });
  }

  private loadConnection(): void {
    this.loading = true;
    this.canvasService.getConnection().subscribe({
      next: (connection) => {
        this.connection = connection;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: (error) =>
        this.failLoading(error, 'Canvas connection information could not be loaded.'),
    });
  }

  private failAction(error: unknown, fallback: string): void {
    this.actionPending = false;
    this.error = extractApiErrorMessage(error, fallback);
    this.cdr.markForCheck();
  }

  private finishTokenRequest(closeReplacement = true): void {
    this.actionPending = false;
    if (closeReplacement) this.replacingToken = false;
    this.accessToken = '';
    this.cdr.markForCheck();
  }

  private failLoading(error: unknown, fallback: string): void {
    this.loading = false;
    this.error = extractApiErrorMessage(error, fallback);
    this.cdr.markForCheck();
  }
}
