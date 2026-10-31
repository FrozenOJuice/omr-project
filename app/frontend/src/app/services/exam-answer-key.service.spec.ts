import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ExamAnswerKeyService } from './exam-answer-key.service';
import {
  CreateExamAnswerKeyRequest,
  ExamAnswerKeyResponse,
  ExtractAnswerKeyScanBatchResponse,
} from '../models/exam-answer-key.model';

const mockKey: ExamAnswerKeyResponse = {
  id: 'key-1',
  exam_id: 'exam-1',
  exam_template_id: 'tmpl-1',
  exam_version: 'A',
  answer_key: { '1': { grading_type: 'single', correct_choices: ['C'], points: null, partial_weights: null } },
  scoring_rules: { points_per_question: 1 },
  answer_key_path: null,
  created_at: '2026-07-01T00:00:00Z',
};

const mockExtraction: ExtractAnswerKeyScanBatchResponse = {
  pages_per_sheet: 1,
  sheets: [],
};

describe('ExamAnswerKeyService', () => {
  let service: ExamAnswerKeyService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ExamAnswerKeyService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('createAnswerKey POSTs to the nested exam route with the body', () => {
    const body: CreateExamAnswerKeyRequest = {
      exam_template_id: 'tmpl-1',
      exam_version: 'A',
      answer_key: { '1': { grading_type: 'single', correct_choices: ['C'] } },
      scoring_rules: { points_per_question: 1 },
    };
    service.createAnswerKey('exam-1', body).subscribe((r) => expect(r).toEqual(mockKey));
    const req = httpMock.expectOne('/api/exams/exam-1/answer-keys');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(body);
    req.flush(mockKey);
  });

  it('listAnswerKeysByExam GETs the nested collection', () => {
    service.listAnswerKeysByExam('exam-1').subscribe((r) => expect(r).toEqual([mockKey]));
    const req = httpMock.expectOne('/api/exams/exam-1/answer-keys');
    expect(req.request.method).toBe('GET');
    req.flush([mockKey]);
  });

  it('extractAnswerKeyScan POSTs the PDFs and question count as multipart form data', () => {
    const fileA = new File(['pdf-a'], 'answer-keys-a.pdf', { type: 'application/pdf' });
    const fileB = new File(['pdf-b'], 'answer-keys-b.pdf', { type: 'application/pdf' });

    service.extractAnswerKeyScan('exam-1', [fileA, fileB], 42).subscribe((r) => expect(r).toEqual(mockExtraction));

    const req = httpMock.expectOne('/api/exams/exam-1/answer-keys/extract-scan');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeInstanceOf(FormData);
    const formData = req.request.body as FormData;
    const uploadedFiles = formData.getAll('files') as File[];
    expect(uploadedFiles.map((f) => f.name)).toEqual(['answer-keys-a.pdf', 'answer-keys-b.pdf']);
    expect(formData.get('question_count')).toBe('42');
    req.flush(mockExtraction);
  });

  it('getAnswerKey GETs the flat by-id route (not nested under the exam)', () => {
    service.getAnswerKey('key-1').subscribe((r) => expect(r).toEqual(mockKey));
    const req = httpMock.expectOne('/api/answer-keys/key-1');
    expect(req.request.method).toBe('GET');
    req.flush(mockKey);
  });

  it('updateAnswerKey PATCHes the by-id route', () => {
    service
      .updateAnswerKey('key-1', { scoring_rules: { points_per_question: 2 } })
      .subscribe((r) => expect(r).toEqual(mockKey));
    const req = httpMock.expectOne('/api/answer-keys/key-1');
    expect(req.request.method).toBe('PATCH');
    req.flush(mockKey);
  });

  it('deleteAnswerKey DELETEs the by-id route', () => {
    service.deleteAnswerKey('key-1').subscribe();
    const req = httpMock.expectOne('/api/answer-keys/key-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });
});
