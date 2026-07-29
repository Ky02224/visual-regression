/** Legacy status type — used internally by StatusBadge component */
export type Status = 'passed' | 'failed' | 'attention' | 'error';

export type ReviewStatus = 'no_changes' | 'unreviewed' | 'approved' | 'rejected';
export type Severity = 'critical' | 'high' | 'medium' | 'low';

/** All defect categories recognised by the AI model (ResNet50 Siamese) */
export type AILabel = 
  | 'missing-element'
  | 'layout-shift'
  | 'color-regression'
  | 'text-truncation'
  | 'overlay-obstruction'
  | 'broken-image'
  | 'misaligned-fields'
  | 'unreadable-text'
  | 'insignificant-change'
  | 'layout-issue'
  | 'text-issue'
  | 'font-change';    // low-contrast or obscured text

export interface Baseline {
  id: string;
  label: string;
  url: string;
  browser: string;
  device: string;
  locale: string;
  updatedAt: string;
  version: string;
  imageUrl: string;
  archivedVersions?: BaselineVersion[];
  /** 'website-capture' for single captures, 'auto-crawl' for multiple crawl captures */
  source: 'website-capture' | 'auto-crawl' | 'local-image';
  /** Hostname extracted from url, e.g. 'example.com' */
  host: string;
  /** Number of archived versions available */
  versionCount: number;
  /** For auto-crawl baselines: the starting URL used for the crawl */
  startUrl?: string;
}

export interface BaselineVersion {
  version: string;
  archivedAt: string;
  imageUrl: string;
}

export interface TestRun {
  id: string;
  name: string;
  /** Legacy — prefer reviewStatus */
  status: Status;
  reviewStatus?: ReviewStatus;
  mismatch: number;
  lastRun: string;
  browser: string;
  device: string;
  locale: string;
  aiInsight?: string;
  aiLabel?: AILabel;
  baselineImage?: string;
  currentImage?: string;
  diffImage?: string;
  reportHref?: string;
  severity?: Severity;
  decisionStatus?: 'approved' | 'rejected' | 'pending';
  lowConfidence?: boolean;
}

export interface DiffRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  area: number;
  meanDelta: number;
}

export interface CompareResult {
  baselineSize: [number, number];
  currentSize: [number, number];
  diffPixels: number;
  totalPixels: number;
  mismatchPct: number;
  ssimScore?: number;
  regions: DiffRegion[];
}

export interface DecisionHistory {
  status: 'approved' | 'rejected';
  decider: string;
  timestamp: string;
  comment?: string;
}

export interface ReportData {
  id: string;
  runId: string;
  baseline: {
    image: string;
    metadata: Record<string, unknown>;
  };
  current: {
    image: string;
    metadata: Record<string, unknown>;
  };
  compareResult: CompareResult;
  aiAssessment: {
    label: AILabel;
    score: number;
    threshold?: number;
  };
  decisionHistory: DecisionHistory[];
}

export interface BatchSummary {
  id: string;
  name: string;
  startedAt: string;
  passed: number;
  failed: number;
  errors: number;
  environment: string;
  totalDuration?: number;
  suiteFile?: string;
}

export interface AIModel {
  id: string;
  name: string;
  architecture: string;
  status: 'production' | 'optimized' | 'training';
  labels: AILabel[];
  trainingSet: string;
  accuracy: number;
  lastRetrained: string;
}

export interface DashboardData {
  runs: TestRun[];
  baselines: Baseline[];
  recentSummaries: BatchSummary[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    pending: number;
  };
  baseline_count?: number;
  // run_count removed — derive from runs.length instead
  pending_decisions?: number;
  approved_decisions?: number;
}

export interface CaptureRequest {
  name: string;
  url: string;
  browser: string;
  device?: string;
  viewport: string;
  locale?: string;
  timezone?: string;
  waitMs?: number;
}

export interface ApiError {
  ok: false;
  error: string;
  code?: string;
  details?: Record<string, unknown>;
}

export interface ApiSuccess<T = unknown> {
  ok: true;
  data: T;
}

export type ApiResponse<T = unknown> = ApiSuccess<T> | ApiError;

/** Raw (snake_case) shapes as returned by GET /api/dashboard — distinct from
 * the camelCase domain types above, which pages map these into as needed. */

export interface RunRowWire {
  id: string;
  mismatch_pct?: number;
  mismatch?: number;
  review_status?: string;
  decision_status?: string;
  status?: string;
  ai_label?: string;
  aiLabel?: string;
  browser?: string;
  device?: string;
  locale?: string;
}

export interface SuiteSummaryCaseWire {
  name: string;
  status: string;
  message?: string;
  report?: string;
  mismatch_pct?: number;
  decision_status?: string;
  ai_label?: string;
}

export interface SuiteSummaryWire {
  file?: string;
  suite?: string;
  suite_name?: string;
  cases?: SuiteSummaryCaseWire[];
  finished_at?: string;
  started_at?: string;
  timestamp?: string | number;
  passed?: number;
  passed_cases?: number;
  failed?: number;
  failed_cases?: number;
  errors?: number;
  total?: number;
  total_cases?: number;
  total_runs?: number;
}

export interface CIBuildWire {
  build_id: string;
  commit_message?: string;
  branch?: string;
  commit_sha?: string;
  passed_count?: number;
  failed_count?: number;
  total_count?: number;
  status?: string;
  created_at?: string | number;
}
