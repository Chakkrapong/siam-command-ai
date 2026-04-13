import type {
  NormalizedExecutionRecord,
  RolloutRawRecord,
  RolloutRouteSummaryItem,
  RolloutRouteSummaryResult,
} from "../types";

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

function toMillis(value: string | undefined): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

function routeNameOf(record: NormalizedExecutionRecord): string {
  return (
    record.derived?.runtimeDecision?.routeName ??
    record.derived?.routeMeta?.routeName ??
    asString(pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "route_name"])) ??
    record.workflowId
  );
}

function isV2Routed(record: NormalizedExecutionRecord): boolean {
  const selectedRuntime = record.derived?.runtimeDecision?.selectedRuntime?.toLowerCase();
  const primaryRuntime = record.derived?.runtimeDecision?.primaryRuntime?.toLowerCase();
  if (selectedRuntime === "v2" || primaryRuntime === "v2") {
    return true;
  }
  const servedRuntime = asString(
    pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "runtime_execution", "served_runtime"]),
  )?.toLowerCase();
  return servedRuntime === "v2";
}

function isSampledV2(record: NormalizedExecutionRecord): boolean {
  const sampled = record.derived?.runtimeDecision?.sampled;
  if (typeof sampled === "boolean") {
    return sampled;
  }
  return (
    asBoolean(pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "runtime_decision", "sampled"])) ??
    false
  );
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

function isPartialV2(record: NormalizedExecutionRecord): boolean {
  if (!isV2Routed(record)) {
    return false;
  }
  const partial = record.derived?.runtimeDecision?.partialEnabled;
  if (typeof partial === "boolean") {
    return partial;
  }
  return (
    asBoolean(
      pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "runtime_decision", "partial_enabled"]),
    ) ?? false
  );
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

interface MutableRouteSummary extends RolloutRouteSummaryItem {
  _lastSeenMs: number;
}

export function aggregateRouteSummary(records: readonly NormalizedExecutionRecord[]): RolloutRouteSummaryResult {
  const byRoute = new Map<string, MutableRouteSummary>();

  for (const record of records) {
    const route = routeNameOf(record);
    const currentLastSeenMs = toMillis(record.receivedAt);
    const existing = byRoute.get(route);
    const summary: MutableRouteSummary =
      existing ??
      ({
        route,
        total: 0,
        sampledV2Count: 0,
        shadowOnlyCount: 0,
        partialV2Count: 0,
        fullV2Count: 0,
        errors: 0,
        lastStateSource: undefined,
        lastPromotionState: undefined,
        lastSeenAt: record.receivedAt,
        _lastSeenMs: currentLastSeenMs,
      } satisfies MutableRouteSummary);

    summary.total += 1;
    if (isSampledV2(record)) {
      summary.sampledV2Count += 1;
    }
    if (isShadowOnly(record)) {
      summary.shadowOnlyCount += 1;
    }
    if (isPartialV2(record)) {
      summary.partialV2Count += 1;
    } else if (isV2Routed(record)) {
      summary.fullV2Count += 1;
    }
    if (isError(record)) {
      summary.errors += 1;
    }

    if (currentLastSeenMs >= summary._lastSeenMs) {
      summary._lastSeenMs = currentLastSeenMs;
      summary.lastSeenAt = record.receivedAt;
      summary.lastStateSource =
        record.derived?.governance?.stateSource ??
        asString(
          pickNested(record.raw as RolloutRawRecord, [
            "runtime_v2_route_meta",
            "execution_report",
            "governance",
            "state_source",
          ]),
        );
      summary.lastPromotionState =
        record.derived?.governance?.promotionState ??
        asString(
          pickNested(record.raw as RolloutRawRecord, [
            "runtime_v2_route_meta",
            "execution_report",
            "governance",
            "promotion_state",
          ]),
        );
    }

    byRoute.set(route, summary);
  }

  const routes: RolloutRouteSummaryItem[] = Array.from(byRoute.values())
    .map(({ _lastSeenMs: _discard, ...item }) => item)
    .sort((a, b) => {
      if (b.total !== a.total) {
        return b.total - a.total;
      }
      return a.route.localeCompare(b.route);
    });

  return { routes };
}
