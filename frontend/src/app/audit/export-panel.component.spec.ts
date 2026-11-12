import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import axe from 'axe-core';

import { ExportPanelComponent } from './export-panel.component';
import { Finding, ReportSummary } from './models';

const summary = (over: Partial<ReportSummary> = {}): ReportSummary => ({
  total: 10, included: 6, approved: 6, unreviewed_included: 0, excluded: 4, excluded_unreviewed: 3, excluded_rejected: 1, ...over,
});

describe('ExportPanelComponent', () => {
  let http: HttpTestingController;
  let el: HTMLElement;
  let fixture: ReturnType<typeof TestBed.createComponent<ExportPanelComponent>>;

  async function load(s: ReportSummary = summary()) {
    fixture = TestBed.createComponent(ExportPanelComponent);
    fixture.componentRef.setInput('auditId', 'a1');
    fixture.componentRef.setInput('findings', [] as Finding[]);
    el = fixture.nativeElement;
    fixture.detectChanges();
    await fixture.whenStable();
    http.expectOne('/api/audits/a1/report/summary').flush(s);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
  });

  it('shows included and excluded counts with the reasons', async () => {
    await load();
    const text = el.textContent!.replace(/\s+/g, ' ');
    expect(text).toContain('6 of 10 findings are included');
    expect(text).toContain('4 are left out: 3 not yet reviewed and 1 rejected');
    expect(text).toContain('Only approved findings are exported');
  });

  it('offers the three formats as a labeled radio group, PDF selected', async () => {
    await load();
    expect(el.querySelector('fieldset legend')?.textContent).toContain('Format');
    const radios = [...el.querySelectorAll<HTMLInputElement>('input[type=radio]')];
    expect(radios.map((r) => r.value)).toEqual(['pdf', 'json', 'xlsx', 'csv']);
    expect(radios[0].checked).toBeTrue();
    radios.forEach((r) => {
      expect(el.querySelector(`label[for="${r.id}"]`)).toBeTruthy();
      expect(el.querySelector(`#${r.getAttribute('aria-describedby')}`)).toBeTruthy();
    });
  });

  it('requests the chosen format and announces the result', async () => {
    await load();
    el.querySelector<HTMLInputElement>('#fmt-csv')!.click();
    fixture.detectChanges();
    const button = el.querySelector<HTMLButtonElement>('button')!;
    expect(button.textContent).toContain('Download CSV');
    button.click();
    const req = http.expectOne((r) => r.url === '/api/audits/a1/report');
    expect(req.request.params.get('format')).toBe('csv');
    req.flush(new Blob(['a,b']), { headers: { 'Content-Disposition': 'attachment; filename="x.csv"' } });
    fixture.detectChanges();
    expect(el.querySelector('[role=status]')?.textContent).toContain('Downloaded x.csv');
  });

  it('reports a failed download in an alert and ignores clicks while busy', async () => {
    await load();
    const button = el.querySelector<HTMLButtonElement>('button')!;
    button.click();
    button.click();
    fixture.detectChanges();
    expect(button.getAttribute('aria-disabled')).toBe('true');
    http.expectOne((r) => r.url === '/api/audits/a1/report').flush(new Blob(['boom']), { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges();
    expect(el.querySelector('[role=alert]')?.textContent).toContain('Could not create the report');
    expect(button.getAttribute('aria-disabled')).toBe('false');
  });

  it('recovers from a failed counts request with Try again', async () => {
    fixture = TestBed.createComponent(ExportPanelComponent);
    fixture.componentRef.setInput('auditId', 'a1');
    fixture.componentRef.setInput('findings', [] as Finding[]);
    el = fixture.nativeElement;
    fixture.detectChanges();
    await fixture.whenStable();
    http.expectOne('/api/audits/a1/report/summary').flush('x', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();
    expect(el.querySelector('[role=alert]')?.textContent).toContain('Could not load the export counts');
    el.querySelector<HTMLButtonElement>('button.retry')!.click();
    http.expectOne('/api/audits/a1/report/summary').flush(summary());
    fixture.detectChanges();
    expect(el.querySelector('[role=alert]')).toBeNull();
    expect(el.textContent).toContain('6 of 10 findings are included');
  });

  it('is operable from the keyboard: every control is natively focusable', async () => {
    await load();
    const controls = el.querySelectorAll('input, button');
    expect(controls.length).toBe(5);
    controls.forEach((c) => expect((c as HTMLElement).tabIndex).toBeGreaterThanOrEqual(0));
  });

  it('has no axe violations, including color contrast', async () => {
    await load();
    document.body.appendChild(el); // contrast checks need the element in the rendered document
    const results = await axe.run(el, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] } });
    expect(results.passes.length).toBeGreaterThan(10); // axe really evaluated the panel
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([]);
  });

  it('has no axe violations in the empty and error states', async () => {
    await load(summary({ included: 0, approved: 0, total: 2, excluded: 2, excluded_unreviewed: 1, excluded_rejected: 1 }));
    document.body.appendChild(el);
    const results = await axe.run(el);
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
