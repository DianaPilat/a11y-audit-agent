import { Routes } from '@angular/router';

import { ReviewComponent } from './audit/review.component';
import { StartComponent } from './audit/start.component';

export const routes: Routes = [
  { path: '', component: StartComponent, title: 'New audit – Accessibility Audit Review' },
  { path: 'audits/:id', component: ReviewComponent, title: 'Review findings – Accessibility Audit Review' },
  { path: '**', redirectTo: '' },
];
