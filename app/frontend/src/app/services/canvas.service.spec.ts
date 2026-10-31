import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { CanvasService } from './canvas.service';

describe('CanvasService', () => {
  let service: CanvasService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(CanvasService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('connects Canvas with a personal access token', () => {
    service.connect('secret-token').subscribe();

    const request = http.expectOne('/api/canvas/connection');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ access_token: 'secret-token' });
    request.flush({ connected: true });
  });

  it('loads Canvas availability from the backend', () => {
    service.getCapabilities().subscribe();

    const request = http.expectOne('/api/canvas/capabilities');
    expect(request.request.method).toBe('GET');
    request.flush({
      configured: true,
      instructor_only: true,
      settings_url: 'http://localhost:6700/profile/settings',
    });
  });

  it('loads the selected Canvas course roster', () => {
    service.getRoster('42').subscribe();

    const request = http.expectOne('/api/canvas/courses/42/students');
    expect(request.request.method).toBe('GET');
    request.flush({ course_id: '42', students: [] });
  });

  it('imports multiple Canvas courses in one backend request', () => {
    service.importCourses(['42', '43']).subscribe();

    const request = http.expectOne('/api/canvas/courses/import');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ course_ids: ['42', '43'] });
    request.flush({ results: [] });
  });

  it('synchronizes an imported course roster', () => {
    service.syncRoster('omr-course-id').subscribe();

    const request = http.expectOne('/api/canvas/imported-courses/omr-course-id/roster/sync');
    expect(request.request.method).toBe('POST');
    request.flush({});
  });

  it('invites one pending roster student', () => {
    service.inviteStudent('omr-course-id', 'roster-entry-id').subscribe();

    const request = http.expectOne(
      '/api/canvas/imported-courses/omr-course-id/roster/roster-entry-id/invite',
    );
    expect(request.request.method).toBe('POST');
    request.flush({});
  });

  it('links a Canvas assignment to an OMR exam', () => {
    const assignmentId = '9007199254740993';
    service.linkExamAssignment('exam-id', assignmentId).subscribe();

    const request = http.expectOne('/api/canvas/exams/exam-id/canvas-assignment');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({ assignment_id: assignmentId });
    request.flush({});
  });

  it('disconnects the local Canvas connection', () => {
    service.disconnect().subscribe();

    const request = http.expectOne('/api/canvas/connection');
    expect(request.request.method).toBe('DELETE');
    request.flush(null);
  });

  it('redeems a student result token without putting it in the URL', () => {
    service.getStudentResult('student-result-token').subscribe();

    const request = http.expectOne('/api/canvas/student-results/access');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ access_token: 'student-result-token' });
    expect(request.request.url).not.toContain('student-result-token');
    request.flush({ id: 'grade-id' });
  });

  it('loads a token-scoped student result page', () => {
    service.getStudentResultPageAnnotations('student-result-token', 2).subscribe();
    service.getStudentResultPageImage('student-result-token', 2).subscribe();

    const annotations = http.expectOne('/api/canvas/student-results/pages/2/annotations');
    expect(annotations.request.method).toBe('POST');
    expect(annotations.request.body).toEqual({ access_token: 'student-result-token' });
    annotations.flush([]);

    const image = http.expectOne('/api/canvas/student-results/pages/2/image');
    expect(image.request.method).toBe('POST');
    expect(image.request.body).toEqual({ access_token: 'student-result-token' });
    expect(image.request.responseType).toBe('blob');
    image.flush(new Blob(['page-image'], { type: 'image/jpeg' }));
  });
});
