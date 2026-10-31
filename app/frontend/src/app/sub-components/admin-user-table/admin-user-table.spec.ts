import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AdminUserTable } from './admin-user-table';
import { AdminUser } from '../../models/admin.model';

describe('AdminUserTable', () => {
  let component: AdminUserTable;
  let fixture: ComponentFixture<AdminUserTable>;

  const mockUsers: AdminUser[] = [
    new AdminUser('1', 'Alice', 'Johnson', 'alice@ubc.ca', 'Professor', 'active', '2026-06-01T00:00:00Z', true),
    new AdminUser('2', 'Bob', 'Smith', 'bob@ubc.ca', 'Student', 'active', '2026-06-01T00:00:00Z', false, '12345678'),
    new AdminUser('3', 'Carol', 'White', 'carol@ubc.ca', 'Admin', 'disabled', '2026-06-01T00:00:00Z', false),
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminUserTable],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminUserTable);
    component = fixture.componentInstance;
    component.users = mockUsers;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should emit filter changes', () => {
    const emitted: Array<{ search: string; role: string; status: string }> = [];
    component.filterChange.subscribe(e => emitted.push(e));

    component.search = 'alice';
    component.role = 'Professor';
    component.status = 'active';
    component.applyFilters();

    expect(emitted[0]).toEqual({
      search: 'alice',
      role: 'Professor',
      status: 'active',
    });
  });

  it('should clear filters', () => {
    const emitted: Array<{ search: string; role: string; status: string }> = [];
    component.filterChange.subscribe(e => emitted.push(e));

    component.search = 'alice';
    component.role = 'Professor';
    component.status = 'active';
    component.clearFilters();

    expect(component.search).toBe('');
    expect(component.role).toBe('');
    expect(component.status).toBe('');
    expect(emitted[0]).toEqual({ search: '', role: '', status: '' });
  });

  it('debounces search input instead of applying filters on every keystroke', () => {
    vi.useFakeTimers();
    const emitted: Array<{ search: string; role: string; status: string }> = [];
    component.filterChange.subscribe(e => emitted.push(e));

    component.search = 'a';
    component.onSearchInput();
    component.search = 'al';
    component.onSearchInput();
    component.search = 'ali';
    component.onSearchInput();

    expect(emitted.length).toBe(0);

    vi.advanceTimersByTime(300);

    expect(emitted.length).toBe(1);
    expect(emitted[0].search).toBe('ali');
    vi.useRealTimers();
  });

  it('flushes a pending debounced search without paging next', () => {
    vi.useFakeTimers();
    component.total = 100;
    component.limit = 25;
    component.offset = 0;

    const events: string[] = [];
    component.filterChange.subscribe(e => events.push(`filter:${e.search}`));
    component.pageChange.subscribe(offset => events.push(`page:${offset}`));

    component.search = 'ali';
    component.onSearchInput();
    component.nextPage();

    expect(events).toEqual(['filter:ali']);
    vi.useRealTimers();
  });

  it('flushes a pending debounced search without paging previous', () => {
    vi.useFakeTimers();
    component.total = 100;
    component.limit = 25;
    component.offset = 25;

    const events: string[] = [];
    component.filterChange.subscribe(e => events.push(`filter:${e.search}`));
    component.pageChange.subscribe(offset => events.push(`page:${offset}`));

    component.search = 'bob';
    component.onSearchInput();
    component.previousPage();

    expect(events).toEqual(['filter:bob']);
    vi.useRealTimers();
  });

  it('pages normally when no search is pending', () => {
    component.total = 100;
    component.limit = 25;
    component.offset = 25;

    const offsets: number[] = [];
    component.pageChange.subscribe(offset => offsets.push(offset));

    component.nextPage();
    component.previousPage();

    expect(offsets).toEqual([50, 0]);
  });
});
