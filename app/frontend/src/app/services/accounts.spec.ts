import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { Accounts } from './accounts';


describe('Accounts', () => {
  let service: Accounts;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(Accounts);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('includes the institution in the existing profile update request', () => {
    service.updateMe(
      'Erin',
      'Lee',
      'elee@university.edu',
      undefined,
      'generic',
    ).subscribe();

    const request = http.expectOne('/api/auth/me');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({
      first_name: 'Erin',
      last_name: 'Lee',
      email: 'elee@university.edu',
      student_number: null,
      institution: 'generic',
    });
    request.flush({});
  });
});
