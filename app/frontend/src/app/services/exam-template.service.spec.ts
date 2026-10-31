import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ExamTemplateService } from './exam-template.service';
import {
  CreateExamTemplateRequest,
  ExamTemplateResponse,
  ExamTemplateUsageResponse,
} from '../models/exam-template.model';

const mockTemplate: ExamTemplateResponse = {
  id: 'tmpl-1',
  name: '100 question A-E',
  created_by: 'user-1',
  question_config: { '1': { choices: ['A', 'B', 'C', 'D', 'E'] } },
  sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1'] }],
  total_questions: 1,
  version: 1,
  n_versions: 4,
  blueprint: null,
  version_from_q1: false,
  omr_template_id: null,
  generated_pdf_path: null,
  archived_at: null,
};

const mockUsage: ExamTemplateUsageResponse = {
  template_id: 'tmpl-1',
  exam_count: 1,
  answer_key_count: 1,
  scan_count: 2,
  exams: [
    {
      id: 'exam-1',
      name: 'Midterm',
      course_id: 'course-1',
      answer_key_count: 1,
      scan_count: 2,
    },
  ],
};

describe('ExamTemplateService', () => {
  let service: ExamTemplateService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ExamTemplateService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('createTemplate POSTs to /api/exam-templates with name and question_config', () => {
    const body: CreateExamTemplateRequest = {
      name: 'Quiz layout',
      question_config: { '1': { choices: ['A', 'B'] } },
      n_versions: 2,
    };
    service.createTemplate(body).subscribe((r) => expect(r).toEqual(mockTemplate));
    const req = httpMock.expectOne('/api/exam-templates');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(body);
    req.flush(mockTemplate);
  });

  it('createUbco100Template POSTs with the blueprint query param and a null body', () => {
    service.createUbco100Template().subscribe((r) => expect(r).toEqual(mockTemplate));
    const req = httpMock.expectOne('/api/exam-templates?blueprint=ubco_100');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeNull();
    req.flush(mockTemplate);
  });

  it('createUbco100Template forwards version_from_q1 when true', () => {
    service.createUbco100Template(true).subscribe();
    const req = httpMock.expectOne('/api/exam-templates?blueprint=ubco_100&version_from_q1=true');
    expect(req.request.method).toBe('POST');
    req.flush(mockTemplate);
  });

  it('createUbco100Template forwards the selected UBCO version count', () => {
    service.createUbco100Template(true, undefined, 3).subscribe();
    const req = httpMock.expectOne(
      '/api/exam-templates?blueprint=ubco_100&version_from_q1=true&n_versions=3',
    );
    expect(req.request.method).toBe('POST');
    req.flush(mockTemplate);
  });

  it('createUbco100Template forwards a trimmed, URL-encoded name when provided', () => {
    service.createUbco100Template(false, ' Midterm 1 ').subscribe();
    const req = httpMock.expectOne('/api/exam-templates?blueprint=ubco_100&name=Midterm%201');
    expect(req.request.method).toBe('POST');
    req.flush(mockTemplate);
  });

  it('listMyTemplates GETs /api/exam-templates/me', () => {
    service.listMyTemplates().subscribe((r) => expect(r).toEqual([mockTemplate]));
    const req = httpMock.expectOne('/api/exam-templates/me');
    expect(req.request.method).toBe('GET');
    req.flush([mockTemplate]);
  });

  it('listMyTemplates can include archived templates', () => {
    service.listMyTemplates(true).subscribe((r) => expect(r).toEqual([mockTemplate]));
    const req = httpMock.expectOne('/api/exam-templates/me?include_archived=true');
    expect(req.request.method).toBe('GET');
    req.flush([mockTemplate]);
  });

  it('listTemplates GETs the full collection', () => {
    service.listTemplates().subscribe((r) => expect(r).toEqual([mockTemplate]));
    const req = httpMock.expectOne('/api/exam-templates');
    expect(req.request.method).toBe('GET');
    req.flush([mockTemplate]);
  });

  it('getTemplate GETs by id', () => {
    service.getTemplate('tmpl-1').subscribe((r) => expect(r).toEqual(mockTemplate));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1');
    expect(req.request.method).toBe('GET');
    req.flush(mockTemplate);
  });

  it('getTemplateUsage GETs by id', () => {
    service.getTemplateUsage('tmpl-1').subscribe((r) => expect(r).toEqual(mockUsage));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/usage');
    expect(req.request.method).toBe('GET');
    req.flush(mockUsage);
  });

  it('updateTemplate PATCHes by id', () => {
    service.updateTemplate('tmpl-1', { name: 'Renamed' }).subscribe((r) => expect(r).toEqual(mockTemplate));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ name: 'Renamed' });
    req.flush(mockTemplate);
  });

  it('deleteTemplate DELETEs by id', () => {
    service.deleteTemplate('tmpl-1').subscribe();
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('deleteTemplate forwards force delete when requested', () => {
    service.deleteTemplate('tmpl-1', true).subscribe();
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1?force=true');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('archiveTemplate POSTs by id', () => {
    service.archiveTemplate('tmpl-1').subscribe();
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/archive');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeNull();
    req.flush({ ...mockTemplate, archived_at: '2026-07-25T12:00:00Z' });
  });

  it('restoreTemplate POSTs by id', () => {
    service.restoreTemplate('tmpl-1').subscribe();
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/restore');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeNull();
    req.flush(mockTemplate);
  });

  it('generatePdf POSTs to the generate route', () => {
    service.generatePdf('tmpl-1').subscribe((r) => expect(r).toEqual(mockTemplate));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/generate');
    expect(req.request.method).toBe('POST');
    req.flush(mockTemplate);
  });

  it('downloadPdf GETs the pdf as a blob (so the auth header is attached)', () => {
    service.downloadPdf('tmpl-1').subscribe((b) => expect(b).toBeInstanceOf(Blob));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/download-pdf');
    expect(req.request.method).toBe('GET');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
  });

  it('finalizeTemplate POSTs by id', () => {
    service.finalizeTemplate('tmpl-1').subscribe((r) => expect(r).toEqual({ ...mockTemplate, omr_template_id: 'omr-1' }));
    const req = httpMock.expectOne('/api/exam-templates/tmpl-1/finalize');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeNull();
    req.flush({ ...mockTemplate, omr_template_id: 'omr-1' });
  });
});
