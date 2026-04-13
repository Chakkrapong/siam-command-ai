import type { RolloutSourceType } from "./types";

export interface RolloutIngestionLimits {
  maxBatchSize: number;
  maxRecordsPerPoll: number;
  maxConcurrentRequests: number;
  requestTimeoutMs: number;
}

export interface RolloutRetentionConfig {
  retentionDays: number;
  archiveAfterDays?: number;
  pruneIntervalMinutes: number;
}

export interface RolloutReadinessThresholdConfig {
  watchScoreThreshold: number;
  holdScoreThreshold: number;
  highErrorRatePct: number;
  moderateErrorRatePct: number;
  rollbackTriggerCount: number;
  overrideTriggerCount: number;
  defaultPolicyTriggerCount: number;
  anomalyTriggerCount: number;
  weights: {
    errorRate: number;
    rollback: number;
    override: number;
    defaultPolicy: number;
    anomalies: number;
  };
}

export interface RolloutDashboardConfig {
  timezone: string;
  defaultLookbackMinutes: number;
  pageSize: number;
  maxPageSize: number;
  enabledSources: RolloutSourceType[];
  ingestion: RolloutIngestionLimits;
  retention: RolloutRetentionConfig;
  readiness: RolloutReadinessThresholdConfig;
}

export const DEFAULT_ROLLOUT_DASHBOARD_CONFIG: RolloutDashboardConfig = {
  timezone: "UTC",
  defaultLookbackMinutes: 60,
  pageSize: 50,
  maxPageSize: 500,
  enabledSources: ["jsonl"],
  ingestion: {
    maxBatchSize: 500,
    maxRecordsPerPoll: 2_000,
    maxConcurrentRequests: 4,
    requestTimeoutMs: 10_000,
  },
  retention: {
    retentionDays: 30,
    archiveAfterDays: 7,
    pruneIntervalMinutes: 60,
  },
  readiness: {
    watchScoreThreshold: 35,
    holdScoreThreshold: 70,
    highErrorRatePct: 5,
    moderateErrorRatePct: 1.5,
    rollbackTriggerCount: 1,
    overrideTriggerCount: 3,
    defaultPolicyTriggerCount: 5,
    anomalyTriggerCount: 8,
    weights: {
      errorRate: 45,
      rollback: 25,
      override: 10,
      defaultPolicy: 10,
      anomalies: 10,
    },
  },
};

export function resolveRolloutDashboardConfig(
  overrides: Partial<RolloutDashboardConfig> = {},
): RolloutDashboardConfig {
  const merged: RolloutDashboardConfig = {
    ...DEFAULT_ROLLOUT_DASHBOARD_CONFIG,
    ...overrides,
    enabledSources: overrides.enabledSources ?? DEFAULT_ROLLOUT_DASHBOARD_CONFIG.enabledSources,
    ingestion: {
      ...DEFAULT_ROLLOUT_DASHBOARD_CONFIG.ingestion,
      ...(overrides.ingestion ?? {}),
    },
    retention: {
      ...DEFAULT_ROLLOUT_DASHBOARD_CONFIG.retention,
      ...(overrides.retention ?? {}),
    },
    readiness: {
      ...DEFAULT_ROLLOUT_DASHBOARD_CONFIG.readiness,
      ...(overrides.readiness ?? {}),
      weights: {
        ...DEFAULT_ROLLOUT_DASHBOARD_CONFIG.readiness.weights,
        ...(overrides.readiness?.weights ?? {}),
      },
    },
  };

  if (merged.pageSize <= 0) {
    throw new Error("rollout config invalid: pageSize must be > 0");
  }
  if (merged.maxPageSize < merged.pageSize) {
    throw new Error("rollout config invalid: maxPageSize must be >= pageSize");
  }
  if (merged.defaultLookbackMinutes <= 0) {
    throw new Error("rollout config invalid: defaultLookbackMinutes must be > 0");
  }
  if (merged.ingestion.maxBatchSize <= 0 || merged.ingestion.maxRecordsPerPoll <= 0) {
    throw new Error("rollout config invalid: ingestion size limits must be > 0");
  }
  if (merged.ingestion.maxConcurrentRequests <= 0) {
    throw new Error("rollout config invalid: maxConcurrentRequests must be > 0");
  }
  if (merged.ingestion.requestTimeoutMs <= 0) {
    throw new Error("rollout config invalid: requestTimeoutMs must be > 0");
  }
  if (merged.retention.retentionDays <= 0 || merged.retention.pruneIntervalMinutes <= 0) {
    throw new Error("rollout config invalid: retention values must be > 0");
  }
  if (merged.retention.archiveAfterDays !== undefined && merged.retention.archiveAfterDays < 0) {
    throw new Error("rollout config invalid: archiveAfterDays must be >= 0");
  }
  if (merged.enabledSources.length === 0) {
    throw new Error("rollout config invalid: enabledSources must not be empty");
  }
  if (merged.readiness.watchScoreThreshold < 0 || merged.readiness.watchScoreThreshold > 100) {
    throw new Error("rollout config invalid: watchScoreThreshold must be in [0,100]");
  }
  if (merged.readiness.holdScoreThreshold < 0 || merged.readiness.holdScoreThreshold > 100) {
    throw new Error("rollout config invalid: holdScoreThreshold must be in [0,100]");
  }
  if (merged.readiness.holdScoreThreshold < merged.readiness.watchScoreThreshold) {
    throw new Error("rollout config invalid: holdScoreThreshold must be >= watchScoreThreshold");
  }
  if (merged.readiness.highErrorRatePct < 0 || merged.readiness.moderateErrorRatePct < 0) {
    throw new Error("rollout config invalid: error rate thresholds must be >= 0");
  }
  if (merged.readiness.highErrorRatePct < merged.readiness.moderateErrorRatePct) {
    throw new Error("rollout config invalid: highErrorRatePct must be >= moderateErrorRatePct");
  }
  if (
    merged.readiness.rollbackTriggerCount < 0 ||
    merged.readiness.overrideTriggerCount < 0 ||
    merged.readiness.defaultPolicyTriggerCount < 0 ||
    merged.readiness.anomalyTriggerCount < 0
  ) {
    throw new Error("rollout config invalid: readiness trigger counts must be >= 0");
  }
  const weightValues = Object.values(merged.readiness.weights);
  if (weightValues.some((value) => value < 0)) {
    throw new Error("rollout config invalid: readiness weights must be >= 0");
  }
  const totalWeight = weightValues.reduce((sum, value) => sum + value, 0);
  if (totalWeight <= 0) {
    throw new Error("rollout config invalid: readiness weights must sum to > 0");
  }

  return merged;
}
