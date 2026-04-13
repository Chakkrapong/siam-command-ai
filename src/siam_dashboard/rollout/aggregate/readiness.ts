import type { RolloutReadinessThresholdConfig } from "../config";
import type {
  RolloutAnomalyAggregate,
  RolloutDashboardMetrics,
  RolloutReadinessLabel,
  RolloutReadinessResult,
} from "../types";

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function normalizeByThreshold(value: number, trigger: number): number {
  if (trigger <= 0) {
    return value > 0 ? 1 : 0;
  }
  return clamp(value / trigger, 0, 1);
}

function buildScore(
  metrics: RolloutDashboardMetrics,
  anomalies: RolloutAnomalyAggregate,
  thresholds: RolloutReadinessThresholdConfig,
): number {
  const errorFactor = clamp(
    metrics.errorRate / Math.max(0.0001, thresholds.highErrorRatePct),
    0,
    1,
  );
  const rollbackFactor = normalizeByThreshold(metrics.rollback.count, thresholds.rollbackTriggerCount);
  const overrideFactor = normalizeByThreshold(metrics.routeOverrideCount, thresholds.overrideTriggerCount);
  const defaultPolicyFactor = normalizeByThreshold(
    anomalies.counts.defaultPolicy,
    thresholds.defaultPolicyTriggerCount,
  );
  const anomalyCount =
    anomalies.counts.defaultPolicy +
    anomalies.counts.conservativeDefault +
    anomalies.counts.failed +
    anomalies.counts.rollbackApplied +
    anomalies.counts.overrideApplied;
  const anomalyFactor = normalizeByThreshold(anomalyCount, thresholds.anomalyTriggerCount);

  const rawWeighted =
    errorFactor * thresholds.weights.errorRate +
    rollbackFactor * thresholds.weights.rollback +
    overrideFactor * thresholds.weights.override +
    defaultPolicyFactor * thresholds.weights.defaultPolicy +
    anomalyFactor * thresholds.weights.anomalies;
  const weightTotal = Object.values(thresholds.weights).reduce((sum, value) => sum + value, 0);

  return Number(((rawWeighted / weightTotal) * 100).toFixed(2));
}

function buildLabel(score: number, thresholds: RolloutReadinessThresholdConfig): RolloutReadinessLabel {
  if (score >= thresholds.holdScoreThreshold) {
    return "Hold";
  }
  if (score >= thresholds.watchScoreThreshold) {
    return "Watch";
  }
  return "Ready";
}

function buildReasons(
  metrics: RolloutDashboardMetrics,
  anomalies: RolloutAnomalyAggregate,
  thresholds: RolloutReadinessThresholdConfig,
  label: RolloutReadinessLabel,
): string[] {
  const reasons: string[] = [];

  if (metrics.errorRate >= thresholds.highErrorRatePct) {
    reasons.push(
      `Error rate is ${metrics.errorRate.toFixed(2)}%, above high threshold ${thresholds.highErrorRatePct.toFixed(2)}%.`,
    );
  } else if (metrics.errorRate >= thresholds.moderateErrorRatePct) {
    reasons.push(
      `Error rate is ${metrics.errorRate.toFixed(2)}%, above moderate threshold ${thresholds.moderateErrorRatePct.toFixed(2)}%.`,
    );
  }

  if (metrics.rollback.count >= thresholds.rollbackTriggerCount && metrics.rollback.count > 0) {
    reasons.push(`Rollback detected (${metrics.rollback.count}) across statuses: ${Object.keys(metrics.rollback.byStatus).join(", ") || "unknown"}.`);
  }

  if (metrics.routeOverrideCount >= thresholds.overrideTriggerCount && metrics.routeOverrideCount > 0) {
    reasons.push(`Route overrides observed (${metrics.routeOverrideCount}).`);
  }

  if (anomalies.counts.defaultPolicy >= thresholds.defaultPolicyTriggerCount && anomalies.counts.defaultPolicy > 0) {
    reasons.push(`Default-policy routing observed ${anomalies.counts.defaultPolicy} times.`);
  }

  const totalAnomalies =
    anomalies.counts.defaultPolicy +
    anomalies.counts.conservativeDefault +
    anomalies.counts.failed +
    anomalies.counts.rollbackApplied +
    anomalies.counts.overrideApplied;
  if (totalAnomalies >= thresholds.anomalyTriggerCount && totalAnomalies > 0) {
    reasons.push(`Total anomaly signals are elevated (${totalAnomalies}).`);
  }

  if (reasons.length === 0) {
    if (label === "Ready") {
      reasons.push("Signals are within configured rollout thresholds.");
    } else if (label === "Watch") {
      reasons.push("Mixed signals detected; monitor rollout closely.");
    } else {
      reasons.push("Risk signals exceed configured tolerance; hold rollout.");
    }
  }

  return reasons;
}

export function scoreRolloutReadiness(
  metrics: RolloutDashboardMetrics,
  anomalies: RolloutAnomalyAggregate,
  thresholds: RolloutReadinessThresholdConfig,
): RolloutReadinessResult {
  const score = buildScore(metrics, anomalies, thresholds);
  const label = buildLabel(score, thresholds);
  const anomalyCount =
    anomalies.counts.defaultPolicy +
    anomalies.counts.conservativeDefault +
    anomalies.counts.failed +
    anomalies.counts.rollbackApplied +
    anomalies.counts.overrideApplied;

  return {
    score,
    label,
    reasons: buildReasons(metrics, anomalies, thresholds, label),
    signals: {
      errorRate: metrics.errorRate,
      rollbackCount: metrics.rollback.count,
      overrideCount: metrics.routeOverrideCount,
      defaultPolicyCount: anomalies.counts.defaultPolicy,
      anomalyCount,
    },
  };
}
