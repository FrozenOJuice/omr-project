import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AdminSessionsTable } from './admin-sessions-table';
import { ActiveSession } from '../../models/admin.model';

describe('AdminSessionsTable', () => {
  let component: AdminSessionsTable;
  let fixture: ComponentFixture<AdminSessionsTable>;

  const mockSessions: ActiveSession[] = [
    new ActiveSession('1', 'Alice Johnson', 'alice@ubc.ca', '5 mins ago'),
    new ActiveSession('2', 'Bob Smith', 'bob@ubc.ca', '1 hr ago'),
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminSessionsTable],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminSessionsTable);
    component = fixture.componentInstance;
    component.sessions = mockSessions;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should render a row for each session', () => {
    const rows = fixture.nativeElement.querySelectorAll('.session-row');
    expect(rows.length).toBe(2);
  });

  it('should emit forceLogout with the correct userId when Force Out is clicked', () => {
    const emitted: string[] = [];
    component.forceLogout.subscribe((id: string) => emitted.push(id));

    const buttons = fixture.nativeElement.querySelectorAll('button');
    buttons[0].click();

    expect(emitted.length).toBe(1);
    expect(emitted[0]).toBe('1');
  });

  it('should show empty state when sessions list is empty', async () => {
    const emptyFixture = TestBed.createComponent(AdminSessionsTable);
    emptyFixture.componentRef.setInput('sessions', []);
    emptyFixture.detectChanges();
    await emptyFixture.whenStable();
    const emptyState = emptyFixture.nativeElement.querySelector('.empty-state');
    expect(emptyState).toBeTruthy();
  });
});
