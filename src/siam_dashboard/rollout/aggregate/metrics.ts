import type { NormalizedExecutionRecord, RolloutDashboardMetrics, RolloutRawRecord } from "../types";

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (value === 1) {
      return true;
    }
    if (value === 0) {
      return false;
    }
    return undefined;
  }
  if (typeof value === "string") {
    const lowered = value.trim().toLowerCase();
    if (["1", "true", "yes"].includes(lowered)) {
      return true;
    }
    if (["0", "false", "no"].includes(lowered)) {
      return false;
    }
  }
  return undefined;
}

function pickNested(raw: Record<string, unknown>, path: ReadonlyArray<string>): unknown {
  let current: unknown = raw;
  for (const key of path) {
    const currentRecord = asRecord(current);
    if (!currentRecord || !(key in currentRecord)) {
      return undefined;
    }
    current = currentRecord[key];
  }
  return current;
}

function percentage(numerator: number, denominator: number): number {
  if (denominator <= 0) {
    return 0;
  }
  return Number(((numerator / denominator) * 100).toFixed(2));
}

function calculateLatencyMs(record: NormalizedExecutionRecord): number | undefined {
  const directLatency =
    record.metrics?.totalDurationMs ??
    record.metrics?.runDurationMs ??
    record.metrics?.queueLatencyMs;
  if (typeof directLatency === "number" && Number.isFinite(directLatency) && directLatency >= 0) {
    return directLatency;
  }

  const startedAt = Date.parse(record.startedAt);
  const endedAt = record.endedAt ? Date.parse(record.endedAt) : Number.NaN;
  if (!Number.isNaN(startedAt) && !Number.isNaN(endedAt) && endedAt >= startedAt) {
    return endedAt - startedAt;
  }

  return undefined;
}

function isV2Routed(record: NormalizedExecutionRecord): boolean {
  const runtimeDecision = record.derived?.runtimeDecision;
  if (runtimeDecision?.selectedRuntime?.toLowerCase() === "v2") {
    return true;
  }
  if (runtimeDecision?.primaryRuntime?.toLowerCase() === "v2") {
    return true;
  }
  if (record.derived?.routeMeta?.event?.toLowerCase() === "routed_v2") {
    return true;
  }

  const runtimeServed = asString(
    pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "runtime_execution", "served_runtime"]),
  );
  return runtimeServed?.toLowerCase() === "v2";
}

function isShadowOnly(record: NormalizedExecutionRecord): boolean {
  if (isV2Routed(record)) {
    return false;
  }

  const shadowEvent = record.derived?.shadow?.event?.toLowerCase();
  const shadowRun = asBoolean(
    pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "execution_report", "shadow", "run"]),
  );
  if (shadowRun === true) {
    return true;
  }
  return shadowEvent === "shadow_match" || shadowEvent === "shadow_diff" || shadowEvent === "shadow_error";
}

function isError(record: NormalizedExecutionRecord): boolean {
  return (
    record.status === "failed" ||
    record.status === "timed_out" ||
    record.severity === "error" ||
    record.severity === "critical" ||
    record.error !== undefined
  );
}

function rollbackStatusOf(record: NormalizedExecutionRecord): string | undefined {
  const governanceRollbackState = record.derived?.governance?.rollbackState;
  if (governanceRollbackState) {
    return governanceRollbackState.toLowerCase();
  }
  const fallback = asString(
    pickNested(record.raw as RolloutRawRecord, [
      "runtime_v2_route_meta",
      "execution_report",
      "governance",
      "rollback_state",
    ]),
  );
  if (fallback) {
    return fallback.toLowerCase();
  }
  return undefined;
}

function isRouteOverride(record: NormalizedExecutionRecord): boolean {
  if (record.derived?.runtimeDecision?.forced) {
    return true;
  }

  const reason =
    record.derived?.runtimeDecision?.reason ??
    record.derived?.routeMeta?.reason ??
    asString(pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "reason"]));
  if (!reason) {
    return false;
  }
  const lowered = reason.toLowerCase();
  return lowered.includes("override") || lowered.includes("manual");
}

export function aggregateRolloutMetrics(records: readonly NormalizedExecutionRecord[]): RolloutDashboardMetrics {
  const totalRequests = records.length;
  if (totalRequests === 0) {
    return {
      totalRequests: 0,
      v2RoutedPercentage: 0,
      shadowOnlyPercentage: 0,
      errorRate: 0,
      averageLatencyMs: null,
      rollback: {
        count: 0,
        byStatus: {},
      },
      routeOverrideCount: 0,
    };
  }

  let v2RoutedCount = 0;
  let shadowOnlyCount = 0;
  let errorCount = 0;
  let routeOverrideCount = 0;
  let latencyTotal = 0;
  let latencyCount = 0;
  const rollbackByStatus: Record<string, number> = {};

  for (const record of records) {
    if (isV2Routed(record)) {
      v2RoutedCount += 1;
    }
    if (isShadowOnly(record)) {
      shadowOnlyCount += 1;
    }
    if (isError(record)) {
      errorCount += 1;
    }
    if (isRouteOverride(record)) {
      routeOverrideCount += 1;
    }

    const rollbackStatus = rollbackStatusOf(record);
    if (rollbackStatus) {
      rollbackByStatus[rollbackStatus] = (rollbackByStatus[rollbackStatus] ?? 0) + 1;
    }

    const latencyMs = calculateLatencyMs(record);
    if (typeof latencyMs === "number") {
      latencyTotal += latencyMs;
      latencyCount += 1;
    }
  }

  const rollbackCount = Object.values(rollbackByStatus).reduce((sum, count) => sum + count, 0);

  return {
    totalRequests,
    v2RoutedPercentage: percentage(v2RoutedCount, totalRequests),
    shadowOnlyPercentage: percentage(shadowOnlyCount, totalRequests),
    errorRate: percentage(errorCount, totalRequests),
    averageLatencyMs: latencyCount > 0 ? Number((latencyTotal / latencyCount).toFixed(2)) : null,
    rollback: {
      count: rollbackCount,
      byStatus: rollbackByStatus,
    },
    routeOverrideCount,
  };
}
