import { Component, EventEmitter, Input, OnDestroy, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AdminUserRow } from '../admin-user-row/admin-user-row';
import { AdminUser, ApiAccountStatus, UserRole } from '../../models/admin.model';

const SEARCH_DEBOUNCE_MS = 300;

@Component({
  selector: 'app-admin-user-table',
  imports: [AdminUserRow, FormsModule],
  templateUrl: './admin-user-table.html',
  styleUrl: './admin-user-table.css',
})
export class AdminUserTable implements OnDestroy {
  @Input() users: AdminUser[] = [];
  @Input() total = 0;
  @Input() limit = 25;
  @Input() offset = 0;
  @Input() search = '';
  @Input() role: UserRole | '' = '';
  @Input() status: ApiAccountStatus | '' = '';
  @Input() isLoading = false;
  @Input() busyUserId: string | null = null;

  private searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  @Output() createUser = new EventEmitter<void>();
  @Output() filterChange = new EventEmitter<{
    search: string;
    role: UserRole | '';
    status: ApiAccountStatus | '';
  }>();
  @Output() pageChange = new EventEmitter<number>();
  @Output() saveUser = new EventEmitter<{
    userId: string;
    firstName: string;
    lastName: string;
    email: string;
    role: UserRole;
    status: ApiAccountStatus;
    studentNumber: string | null;
  }>();
  @Output() forceLogout = new EventEmitter<string>();
  @Output() deleteUser = new EventEmitter<AdminUser>();
  @Output() resendSetupEmail = new EventEmitter<AdminUser>();

  readonly roles: Array<UserRole | ''> = ['', 'Admin', 'Professor', 'Student'];
  readonly statuses: Array<ApiAccountStatus | ''> = ['', 'active', 'disabled'];

  get pageStart(): number {
    return this.total === 0 ? 0 : this.offset + 1;
  }

  get pageEnd(): number {
    return Math.min(this.offset + this.limit, this.total);
  }

  get canGoPrevious(): boolean {
    return this.offset > 0;
  }

  get canGoNext(): boolean {
    return this.offset + this.limit < this.total;
  }

  applyFilters(): void {
    this.filterChange.emit({
      search: this.search.trim(),
      role: this.role,
      status: this.status,
    });
  }

  // Debounced so each keystroke in the search box doesn't trigger its own
  // dashboard reload -- the parent's isLoading flag flips on every reload,
  // and that used to unmount/remount this whole table (see admin-dashboard),
  // yanking focus out of the input the user was still typing in.
  onSearchInput(): void {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
    }
    this.searchDebounceTimer = setTimeout(() => this.applyFilters(), SEARCH_DEBOUNCE_MS);
  }

  // Called before emitting pageChange so a page-button click while a search
  // debounce is pending doesn't load the new page against the stale
  // pre-edit search term.
  private flushPendingSearch(): boolean {
    if (!this.searchDebounceTimer) return false;

    clearTimeout(this.searchDebounceTimer);
    this.searchDebounceTimer = null;
    this.applyFilters();
    return true;
  }

  clearFilters(): void {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = null;
    }
    this.search = '';
    this.role = '';
    this.status = '';
    this.applyFilters();
  }

  ngOnDestroy(): void {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
    }
  }

  previousPage(): void {
    if (this.canGoPrevious && !this.flushPendingSearch()) {
      this.pageChange.emit(Math.max(this.offset - this.limit, 0));
    }
  }

  nextPage(): void {
    if (this.canGoNext && !this.flushPendingSearch()) {
      this.pageChange.emit(this.offset + this.limit);
    }
  }
}
