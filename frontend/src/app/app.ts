import { Component } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  template: `
    <a class="skip-link" href="#main">Skip to main content</a>
    <header>
      <a routerLink="/" class="brand">Accessibility Audit Review</a>
    </header>
    <main id="main" tabindex="-1">
      <router-outlet />
    </main>
  `,
})
export class App {}
