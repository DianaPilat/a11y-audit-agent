export type ReviewStatus = 'pending' | 'approved' | 'rejected';
export type Severity = 'critical' | 'serious' | 'moderate' | 'minor';
export type AuditStatus = 'queued' | 'running' | 'done' | 'failed';

export interface Audit {
  id: string;
  url: string;
  max_pages: number;
  status: AuditStatus;
  phase: string;
  pages_total: number;
  pages_done: number;
  pages_failed: number;
  error: string | null;
  created_at: string;
  findings_count?: number;
  review_counts?: Record<ReviewStatus, number>;
}

export interface Finding {
  id: number;
  audit_id: string;
  url: string;
  rule_id: string;
  wcag_criterion: string;
  severity: Severity;
  element: string;
  explanation: string;
  source: 'axe-core' | 'ai-assessed';
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  review_status: ReviewStatus;
}

export const SEVERITY_ORDER: Severity[] = ['critical', 'serious', 'moderate', 'minor'];

export const PHASE_LABELS: Record<string, string> = {
  queued: 'Waiting to start',
  crawling: 'Finding pages',
  auditing: 'Auditing pages',
  writing_tickets: 'Drafting tickets',
  done: 'Finished',
  failed: 'Failed',
};
