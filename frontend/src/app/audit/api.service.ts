import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Audit, Finding, ReviewStatus } from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  startAudit(url: string, maxPages: number): Observable<Audit> {
    return this.http.post<Audit>(`${this.base}/audits`, { url, max_pages: maxPages });
  }

  listAudits(): Observable<Audit[]> {
    return this.http.get<Audit[]>(`${this.base}/audits`);
  }

  getAudit(id: string): Observable<Audit> {
    return this.http.get<Audit>(`${this.base}/audits/${id}`);
  }

  listFindings(id: string): Observable<Finding[]> {
    return this.http.get<Finding[]>(`${this.base}/audits/${id}/findings`);
  }

  review(auditId: string, findingId: number, status: ReviewStatus): Observable<Finding> {
    return this.http.patch<Finding>(`${this.base}/audits/${auditId}/findings/${findingId}`, { status });
  }
}
