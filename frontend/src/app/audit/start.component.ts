import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { ApiService } from './api.service';
import { formatFull, formatWhen, parseUtc } from './format-time';
import { Audit, PHASE_LABELS } from './models';

@Component({
  selector: 'app-start',
  imports: [FormsModule, RouterLink],
  template: `
    <span class="eyebrow">WCAG 2.1 AA</span>
    <h1>Audit a website</h1>
    <p class="lede">
      Enter a site address. The agent crawls it, checks each page against WCAG 2.1 AA, and lists what it finds
      for you to approve or reject.
    </p>

    <form (ngSubmit)="start()" class="card card-form">
      <div class="fields">
        <div class="field">
          <label for="url">Site address</label>
          <input id="url" name="url" type="url" required autocomplete="url" placeholder="https://example.com"
                 [(ngModel)]="url" [attr.aria-describedby]="error() ? 'url-error' : null"
                 [attr.aria-invalid]="error() ? 'true' : null" />
        </div>
        <div class="field">
          <label for="pages">Maximum pages</label>
          <input id="pages" name="pages" type="number" min="1" max="20" required [(ngModel)]="maxPages" />
        </div>
      </div>
      @if (error()) {
        <p id="url-error" class="error" role="alert">{{ error() }}</p>
      }
      <button type="submit" class="primary" [disabled]="starting()">
        {{ starting() ? 'Starting…' : 'Start audit' }}
      </button>
    </form>

    @if (audits().length) {
      <h2>Previous audits</h2>
      <ul class="plain list">
        @for (a of audits(); track a.id) {
          <li class="card card-link row">
            <div>
              <a [routerLink]="['/audits', a.id]">{{ a.url }}</a>
              <div class="meta">
                <time [attr.datetime]="iso(a)" [title]="full(a)">{{ when(a) }}</time>
              </div>
            </div>
            <span class="badge" [attr.data-phase]="phaseKey(a)">{{ phase(a) }}</span>
          </li>
        }
      </ul>
    }
  `,
})
export class StartComponent {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  url = '';
  maxPages = 20;
  readonly error = signal('');
  readonly starting = signal(false);
  readonly audits = signal<Audit[]>([]);

  constructor() {
    this.api.listAudits().subscribe({ next: (a) => this.audits.set(a), error: () => {} });
  }

  phase(a: Audit): string {
    return a.status === 'failed' ? 'Failed' : (PHASE_LABELS[a.phase] ?? a.phase);
  }

  when(a: Audit): string {
    return formatWhen(a.created_at);
  }

  full(a: Audit): string {
    return formatFull(a.created_at);
  }

  iso(a: Audit): string {
    return parseUtc(a.created_at).toISOString();
  }

  phaseKey(a: Audit): string {
    return a.status === 'failed' ? 'failed' : a.phase;
  }

  start(): void {
    this.error.set('');
    this.starting.set(true);
    this.api.startAudit(this.url.trim(), this.maxPages).subscribe({
      next: (audit) => this.router.navigate(['/audits', audit.id]),
      error: (e) => {
        this.starting.set(false);
        this.error.set(
          e.status === 422
            ? 'Enter a full address starting with http:// or https://, and 1–20 pages.'
            : 'Could not reach the audit server. Is the backend running?',
        );
      },
    });
  }
}
