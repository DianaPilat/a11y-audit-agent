import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import { Audit, Finding } from './models';
import { ReviewComponent } from './review.component';

const audit = (over: Partial<Audit> = {}): Audit => ({
  id: 'a1', url: 'http://x/', max_pages: 20, status: 'running', phase: 'auditing',
  pages_total: 4, pages_done: 1, pages_failed: 0, error: null, created_at: '2026-11-10 10:00:00', ...over,
});
const finding = (id: number, over: Partial<Finding> = {}): Finding => ({
  id, audit_id: 'a1', url: 'http://x/', rule_id: 'image-alt', wcag_criterion: '1.1.1', severity: 'serious',
  element: `img.n${id}`, explanation: 'Screen reader users hear nothing for this image.', review_status: 'pending', ...over,
});

describe('ReviewComponent', () => {
  let http: HttpTestingController;
  let el: HTMLElement;
  let fixture: ReturnType<typeof TestBed.createComponent<ReviewComponent>>;

  function respond(a: Audit, f: Finding[]) {
    http.expectOne('/api/audits/a1').flush(a);
    http.expectOne('/api/audits/a1/findings').flush(f);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(), provideHttpClientTesting(), provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: new Map([['id', 'a1']]) } } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ReviewComponent);
    el = fixture.nativeElement;
    fixture.detectChanges();
  });

  it('shows progress while running', () => {
    respond(audit(), [finding(1)]);
    expect(el.textContent).toContain('1 of 4 pages done');
    expect(el.querySelector('progress')?.getAttribute('value')).toBe('25');
    expect(el.querySelectorAll('li.finding').length).toBe(1);
  });

  it('approves a finding and updates counts', () => {
    respond(audit({ status: 'done', phase: 'done', pages_done: 4 }), [finding(1), finding(2)]);
    const approve = el.querySelector<HTMLButtonElement>('button.approve')!;
    expect(approve.getAttribute('aria-label')).toContain('img.n1');
    approve.click();
    const req = http.expectOne('/api/audits/a1/findings/1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ status: 'approved' });
    req.flush(finding(1, { review_status: 'approved' }));
    fixture.detectChanges();
    expect(el.querySelector('li.finding .status')?.textContent).toContain('Approved');
    expect(el.querySelector('li.finding button.undo')).toBeTruthy();
    const chips = [...el.querySelectorAll('.chip')].map((c) => c.textContent!.replace(/\s+/g, ' ').trim());
    expect(chips).toContain('Needs review 1');
    expect(chips).toContain('Approved 1');
  });

  it('filters the list and orders by severity', () => {
    respond(audit({ status: 'done', phase: 'done' }), [
      finding(1, { severity: 'minor' }), finding(2, { severity: 'critical', review_status: 'rejected' }),
    ]);
    const order = [...el.querySelectorAll('li.finding h3')].map((h) => h.textContent);
    expect(el.querySelector('li.finding .badge')?.textContent).toContain('critical');
    expect(order.length).toBe(2);
    el.querySelectorAll<HTMLButtonElement>('.chip')[3].click(); // Rejected
    fixture.detectChanges();
    expect(el.querySelectorAll('li.finding').length).toBe(1);
  });

  it('shows the first sentence and tucks the rest behind details', () => {
    respond(audit({ status: 'done', phase: 'done' }), [
      finding(1, { explanation: 'First point. Second point with more detail.' }), finding(2),
    ]);
    const [one, two] = [...el.querySelectorAll('li.finding')];
    expect(one.querySelector('.lead')?.textContent).toBe('First point.');
    expect(one.querySelector('details')).toBeTruthy();
    expect(two.querySelector('details')).toBeNull();
  });

  it('shows the failure reason', () => {
    respond(audit({ status: 'failed', phase: 'failed', error: 'browser died' }), []);
    expect(el.querySelector('[role=alert]')?.textContent).toContain('browser died');
  });
});
