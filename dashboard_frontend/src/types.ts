/** Legacy status type — used internally by StatusBadge component */
export type Status = 'passed' | 'failed' | 'attention' | 'error';

export type ReviewStatus = 'no_changes' | 'unreviewed' | 'approved' | 'rejected';
export type Severity = 'critical' | 'high' | 'medium' | 'low';

/** All 8 defect categories recognised by the AI model (ResNet50 Siamese) */
export type AILabel = 
  | 'missing-element'     // UI element is absent
  | 'layout-shift'        // structural position change
  | 'color-regression'    // unexpected colour change
  | 'text-truncation'     // clipped or shortened text
  | 'overlay-obstruction' // modal / banner blocking content
  | 'broken-image'        // image failed to load
  | 'misaligned-fields'   // form fields / elements out of position
  | 'unreadable-text';    // low-contrast or obscured text

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
  run_count?: number;
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
