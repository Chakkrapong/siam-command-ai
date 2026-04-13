export type RolloutSourceType = "jsonl" | "api" | "db";
export type RolloutRawRecord = Record<string, unknown>;

export type ExecutionStatus = "queued" | "running" | "succeeded" | "failed" | "canceled" | "timed_out";

export type SeverityLevel = "info" | "warning" | "error" | "critical";

export interface ExecutionActor {
  id: string;
  type: "system" | "operator" | "service_account";
  displayName?: string;
}

export interface ExecutionMetrics {
  queueLatencyMs?: number;
  runDurationMs?: number;
  totalDurationMs?: number;
  retries?: number;
  cpuPct?: number;
  memoryMb?: number;
}

export interface ExecutionErrorInfo {
  code: string;
  message: string;
  details?: string;
  retryable?: boolean;
}

export interface RuntimeDecisionSnapshot {
  routeName?: string;
  selectedRuntime?: string;
  primaryRuntime?: string;
  reason?: string;
  partialEnabled?: boolean;
  allowlisted?: boolean;
  inRollout?: boolean;
  guardBlocked?: boolean;
  guardReason?: string;
  riskLevel?: string;
  riskReason?: string;
  rolloutPercent?: number;
  rolloutBucket?: number;
  sampled?: boolean;
  forced?: boolean;
  autoDisabled?: boolean;
}

export interface GovernanceSnapshot {
  promotionState?: string;
  routeFamily?: string;
  stateSource?: string;
  downgraded?: boolean;
  downgradeReason?: string;
  rollbackState?: string;
}

export interface DecisionTraceSnapshot {
  selectedCommand?: string;
  selectedTool?: string;
  policyName?: string;
  reason?: string;
}

export interface RouteMetaSnapshot {
  event?: string;
  routeName?: string;
  commandName?: string;
  reason?: string;
}

export interface ShadowSnapshot {
  event?: string;
  reason?: string;
  match?: boolean;
  errorKind?: string;
}

export interface NormalizedRecordDerived {
  runtimeDecision?: RuntimeDecisionSnapshot;
  governance?: GovernanceSnapshot;
  decisionTrace?: DecisionTraceSnapshot;
  routeMeta?: RouteMetaSnapshot;
  shadow?: ShadowSnapshot;
}

export interface NormalizedExecutionRecord {
  id: string;
  workflowId: string;
  workflowVersion?: string;
  rolloutId: string;
  runbookId?: string;
  environment: string;
  service: string;
  region?: string;
  startedAt: string;
  endedAt?: string;
  receivedAt: string;
  status: ExecutionStatus;
  severity: SeverityLevel;
  actor: ExecutionActor;
  tags: string[];
  metrics?: ExecutionMetrics;
  error?: ExecutionErrorInfo;
  sourceType: RolloutSourceType;
  sourceRef: string;
  sourceOffset?: string | number;
  sourceIngestedAt: string;
  derived?: NormalizedRecordDerived;
  raw: RolloutRawRecord;
}

export interface RolloutRecordFilter {
  environments?: string[];
  services?: string[];
  statuses?: ExecutionStatus[];
  severities?: SeverityLevel[];
  workflowIds?: string[];
  rolloutIds?: string[];
  regions?: string[];
  tags?: string[];
  startedAtFrom?: string;
  startedAtTo?: string;
}

export type RolloutRecordSortField = "startedAt" | "endedAt" | "receivedAt" | "sourceIngestedAt";

export interface RolloutRecordSort {
  field: RolloutRecordSortField;
  direction: "asc" | "desc";
}

export interface RolloutQuery {
  filter?: RolloutRecordFilter;
  sort?: RolloutRecordSort;
  limit?: number;
  cursor?: string;
}

export interface RolloutQueryResult {
  records: NormalizedExecutionRecord[];
  nextCursor?: string;
}

export interface RollbackMetrics {
  count: number;
  byStatus: Record<string, number>;
}

export interface RolloutDashboardMetrics {
  totalRequests: number;
  v2RoutedPercentage: number;
  shadowOnlyPercentage: number;
  errorRate: number;
  averageLatencyMs: number | null;
  rollback: RollbackMetrics;
  routeOverrideCount: number;
}

export interface RolloutRouteSummaryItem {
  route: string;
  total: number;
  sampledV2Count: number;
  shadowOnlyCount: number;
  partialV2Count: number;
  fullV2Count: number;
  errors: number;
  lastStateSource?: string;
  lastPromotionState?: string;
  lastSeenAt: string;
}

export interface RolloutRouteSummaryResult {
  routes: RolloutRouteSummaryItem[];
}

export type RolloutAnomalyKind =
  | "default_policy"
  | "conservative_default"
  | "failed"
  | "rollback_applied"
  | "override_applied";

export interface RolloutAnomalySliceItem {
  recordId: string;
  route: string;
  receivedAt: string;
  kinds: RolloutAnomalyKind[];
  reason?: string;
  stateSource?: string;
  promotionState?: string;
}

export interface RolloutAnomalyCounts {
  defaultPolicy: number;
  conservativeDefault: number;
  failed: number;
  rollbackApplied: number;
  overrideApplied: number;
}

export interface RolloutAnomalyAggregate {
  counts: RolloutAnomalyCounts;
  recent: RolloutAnomalySliceItem[];
}

export type RolloutReadinessLabel = "Ready" | "Watch" | "Hold";

export interface RolloutReadinessSignals {
  errorRate: number;
  rollbackCount: number;
  overrideCount: number;
  defaultPolicyCount: number;
  anomalyCount: number;
}

export interface RolloutReadinessResult {
  score: number;
  label: RolloutReadinessLabel;
  reasons: string[];
  signals: RolloutReadinessSignals;
}

export interface RolloutDashboardLoadRequest {
  sourceType?: RolloutSourceType;
  sourceId?: string;
  cursor?: string;
  signal?: AbortSignal;
}

export interface RolloutDashboardIngestionState {
  sourceType: RolloutSourceType;
  sourceRef: string;
  nextCursor?: string;
  hasMore: boolean;
  malformedLineCount: number;
}

export interface RolloutDashboardViewModel {
  generatedAt: string;
  ingestion: RolloutDashboardIngestionState;
  records: NormalizedExecutionRecord[];
  metrics: RolloutDashboardMetrics;
  routeSummary: RolloutRouteSummaryResult;
  anomalies: RolloutAnomalyAggregate;
  readiness: RolloutReadinessResult;
}

export interface RolloutDashboardServiceContract {
  loadViewModel(request?: RolloutDashboardLoadRequest): Promise<RolloutDashboardViewModel>;
}
