export type Status = 'passed' | 'failed' | 'attention' | 'error';

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
}

export interface TestRun {
  id: string;
  name: string;
  status: Status;
  mismatch: number;
  lastRun: string;
  browser: string;
  device: string;
  locale: string;
  aiInsight?: string;
  aiLabel?: string;
  baselineImage?: string;
  currentImage?: string;
  diffImage?: string;
  reportHref?: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
}

export interface BatchSummary {
  id: string;
  name: string;
  startedAt: string;
  passed: number;
  failed: number;
  errors: number;
  environment: string;
}

export interface AIModel {
  id: string;
  name: string;
  architecture: string;
  status: 'production' | 'optimized' | 'training';
  labels: string[];
  trainingSet: string;
  accuracy: number;
  lastRetrained: string;
}
