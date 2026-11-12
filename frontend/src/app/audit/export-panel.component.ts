import { Component, effect, inject, input, signal } from '@angular/core';

import { ApiService } from './api.service';
import { Finding, ReportFormat, ReportSummary } from './models';

const FORMATS: { value: ReportFormat; label: string; hint: string }[] = [
  { value: 'pdf', label: 'PDF report', hint: 'Accessible tagged PDF for clients: summary, findings table, details and limitations.' },
  { value: 'json', label: 'JSON', hint: 'Every field of each included finding, for other tools.' },
  { value: 'xlsx', label: 'Excel (.xlsx)', hint: 'One row per issue, formatted for reading in Excel: wrapped text and sized columns.' },
  { value: 'csv', label: 'CSV', hint: 'One row per issue, plain text with no formatting, for importing into other tools.' },
];

@Component({
  selector: 'app-export-panel',
  templateUrl: './export-panel.component.html',
})
export class ExportPanelComponent {
  private readonly api = inject(ApiService);

  readonly auditId = input.required<string>();
  /** Reloading counts whenever the review list changes keeps the panel in step with approvals. */
  readonly findings = input.required<Finding[]>();

  readonly formats = FORMATS;
  readonly format = signal<ReportFormat>('pdf');
  readonly summary = signal<ReportSummary | null>(null);
  readonly summaryError = signal('');
  readonly busy = signal(false);
  readonly status = signal('');
  readonly error = signal('');

  private request = 0;

  constructor() {
    effect(() => {
      this.findings();
      this.loadSummary();
    });
  }

  loadSummary(): void {
    const mine = ++this.request;
    this.api.reportSummary(this.auditId()).subscribe({
      next: (s) => {
        if (mine !== this.request) return; // a newer request superseded this one
        this.summary.set(s);
        this.summaryError.set('');
      },
      error: () => mine === this.request && this.summaryError.set('Could not load the export counts.'),
    });
  }

  download(): void {
    if (this.busy()) return; // aria-disabled keeps the button focusable, so guard here
    const format = this.format();
    this.busy.set(true);
    this.error.set('');
    this.status.set('Preparing the report…');
    this.api.downloadReport(this.auditId(), format).subscribe({
      next: (res) => {
        const name =
          /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? `accessibility-assessment.${format}`;
        const url = URL.createObjectURL(res.body!);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.click();
        URL.revokeObjectURL(url);
        this.busy.set(false);
        this.status.set(`Downloaded ${name}.`);
      },
      error: () => {
        this.busy.set(false);
        this.status.set('');
        this.error.set('Could not create the report. Try again, or check that the backend is running.');
      },
    });
  }
}
