import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AcademicTerm,
  CreateAcademicTermRequest,
  UpdateAcademicTermRequest,
} from '../models/academic-term.model';
import { InstitutionCode } from '../models/institution.model';

@Injectable({ providedIn: 'root' })
export class AcademicTermService {
  private http = inject(HttpClient);

  listTerms(options: {
    institution?: InstitutionCode;
    includeArchived?: boolean;
  } = {}): Observable<AcademicTerm[]> {
    let params = new HttpParams();
    if (options.institution) {
      params = params.set('institution', options.institution);
    }
    if (options.includeArchived) {
      params = params.set('include_archived', true);
    }
    return this.http.get<AcademicTerm[]>('/api/academic-terms', { params });
  }

  createTerm(request: CreateAcademicTermRequest): Observable<AcademicTerm> {
    return this.http.post<AcademicTerm>('/api/academic-terms', request);
  }

  updateTerm(termId: string, request: UpdateAcademicTermRequest): Observable<AcademicTerm> {
    return this.http.patch<AcademicTerm>(`/api/academic-terms/${termId}`, request);
  }

  deleteTerm(termId: string): Observable<void> {
    return this.http.delete<void>(`/api/academic-terms/${termId}`);
  }
}
