import { Component, EventEmitter, Input, Output } from '@angular/core';
import { ActiveSession } from '../../models/admin.model';

@Component({
  selector: 'app-admin-sessions-table',
  imports: [],
  templateUrl: './admin-sessions-table.html',
  styleUrl: './admin-sessions-table.css',
})
export class AdminSessionsTable {
  @Input() sessions: ActiveSession[] = [];
  @Output() forceLogout = new EventEmitter<string>();
}
