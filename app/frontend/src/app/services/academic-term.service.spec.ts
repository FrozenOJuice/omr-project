import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AcademicTermService } from './academic-term.service';

describe('AcademicTermService', () => {
  let service: AcademicTermService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AcademicTermService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists archived terms for a selected institution', () => {
    service.listTerms({ institution: 'generic', includeArchived: true }).subscribe();

    const request = http.expectOne(request => request.url === '/api/academic-terms');
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('institution')).toBe('generic');
    expect(request.request.params.get('include_archived')).toBe('true');
    request.flush([]);
  });

  it('creates, updates, and deletes terms through the term API', () => {
    const draft = {
      name: 'Trimester 1',
      term_type: 'preset' as const,
      institution: 'generic' as const,
      year_format: 'start_year' as const,
    };
    service.createTerm(draft).subscribe();
    const create = http.expectOne('/api/academic-terms');
    expect(create.request.method).toBe('POST');
    expect(create.request.body).toEqual(draft);
    create.flush({});

    service.updateTerm('term-1', { is_active: false }).subscribe();
    const update = http.expectOne('/api/academic-terms/term-1');
    expect(update.request.method).toBe('PATCH');
    expect(update.request.body).toEqual({ is_active: false });
    update.flush({});

    service.deleteTerm('term-1').subscribe();
    const remove = http.expectOne('/api/academic-terms/term-1');
    expect(remove.request.method).toBe('DELETE');
    remove.flush(null);
  });
});
