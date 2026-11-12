import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EMPTY, catchError, forkJoin, interval, startWith, switchMap, takeWhile } from 'rxjs';

import { ApiService } from './api.service';
import { Audit, Finding, PHASE_LABELS, ReviewStatus, SEVERITY_ORDER } from './models';

type Filter = 'all' | ReviewStatus;

const POLL_MS = 2000;

@Component({
  selector: 'app-review',
  imports: [RouterLink],
  templateUrl: './review.component.html',
})
export class ReviewComponent {
  private readonly api = inject(ApiService);
  private readonly auditId = inject(ActivatedRoute).snapshot.paramMap.get('id')!;

  readonly audit = signal<Audit | null>(null);
  readonly findings = signal<Finding[]>([]);
  readonly loadError = signal('');
  readonly actionError = signal('');
  readonly filter = signal<Filter>('all');
  readonly announcement = signal('');

  readonly running = computed(() => {
    const s = this.audit()?.status;
    return s === 'queued' || s === 'running';
  });
  readonly phaseLabel = computed(() => PHASE_LABELS[this.audit()?.phase ?? ''] ?? this.audit()?.phase ?? '');
  readonly progressPercent = computed(() => {
    const a = this.audit();
    if (!a) return 0;
    if (a.status === 'done') return 100;
    return a.pages_total ? Math.round((a.pages_done / a.pages_total) * 100) : 0;
  });
  readonly counts = computed(() => {
    const c = { all: 0, pending: 0, approved: 0, rejected: 0 };
    for (const f of this.findings()) {
      c.all++;
      c[f.review_status]++;
    }
    return c;
  });
  readonly visible = computed(() => {
    const f = this.filter();
    return this.findings()
      .filter((x) => f === 'all' || x.review_status === f)
      .sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || a.id - b.id);
  });
  readonly filters: { value: Filter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'pending', label: 'Needs review' },
    { value: 'approved', label: 'Approved' },
    { value: 'rejected', label: 'Rejected' },
  ];

  constructor() {
    // Poll while the audit runs; takeWhile's inclusive flag delivers the final poll before stopping.
    interval(POLL_MS)
      .pipe(
        startWith(0),
        switchMap(() =>
          forkJoin([this.api.getAudit(this.auditId), this.api.listFindings(this.auditId)]).pipe(
            catchError(() => {
              this.loadError.set('Could not load this audit. Check that the backend is running.');
              return EMPTY;
            }),
          ),
        ),
        takeWhile(([audit]) => audit.status === 'queued' || audit.status === 'running', true),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe(([audit, findings]) => {
        this.loadError.set('');
        this.audit.set(audit);
        this.findings.set(findings);
        if (audit.status === 'done') this.announcement.set(`Audit finished. ${findings.length} findings to review.`);
        if (audit.status === 'failed') this.announcement.set('Audit failed.');
      });
  }

  set(finding: Finding, status: ReviewStatus): void {
    this.actionError.set('');
    this.api.review(this.auditId, finding.id, status).subscribe({
      next: (updated) => {
        this.findings.update((all) => all.map((f) => (f.id === updated.id ? updated : f)));
        this.announcement.set(`Finding ${finding.rule_id} ${status === 'pending' ? 'reset to needs review' : status}.`);
      },
      error: () => this.actionError.set('Could not save that decision. Try again.'),
    });
  }

  /** First sentence of an explanation, so each card scans in one line; the rest sits behind "More detail". */
  lead(text: string): string {
    const m = text.match(/^.*?[.!?](?=\s|$)/s);
    return m ? m[0] : text;
  }

  hasMore(text: string): boolean {
    return this.lead(text).length < text.trim().length;
  }

  statusLabel(s: ReviewStatus): string {
    return s === 'pending' ? 'Needs review' : s === 'approved' ? 'Approved' : 'Rejected';
  }
}
