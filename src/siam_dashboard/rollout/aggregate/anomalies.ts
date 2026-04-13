import type {
  NormalizedExecutionRecord,
  RolloutAnomalyAggregate,
  RolloutAnomalyKind,
  RolloutAnomalySliceItem,
  RolloutRawRecord,
} from "../types";

const DEFAULT_RECENT_LIMIT = 25;

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

function reasonOf(record: NormalizedExecutionRecord): string | undefined {
  return (
    record.derived?.runtimeDecision?.reason ??
    record.derived?.routeMeta?.reason ??
    asString(pickNested(record.raw as RolloutRawRecord, ["runtime_v2_route_meta", "reason"]))
  );
}

function isFailed(record: NormalizedExecutionRecord): boolean {
  return (
    record.status === "failed" ||
    record.status === "timed_out" ||
    record.severity === "error" ||
    record.severity === "critical" ||
    record.error !== undefined
  );
}

function isDefaultPolicy(record: NormalizedExecutionRecord): boolean {
  const stateSource =
    record.derived?.governance?.stateSource ??
    asString(
      pickNested(record.raw as RolloutRawRecord, [
        "runtime_v2_route_meta",
        "execution_report",
        "governance",
        "state_source",
      ]),
    );
  return stateSource?.toLowerCase() === "default_policy";
}

function isConservativeDefault(record: NormalizedExecutionRecord): boolean {
  const reason = reasonOf(record)?.toLowerCase() ?? "";
  const riskReason = record.derived?.runtimeDecision?.riskReason?.toLowerCase() ?? "";
  return reason.includes("conservative_default") || riskReason.includes("conservative_default");
}

function isRollbackApplied(record: NormalizedExecutionRecord): boolean {
  const rollbackState =
    record.derived?.governance?.rollbackState ??
    asString(
      pickNested(record.raw as RolloutRawRecord, [
        "runtime_v2_route_meta",
        "execution_report",
        "governance",
        "rollback_state",
      ]),
    );
  if (rollbackState) {
    const lowered = rollbackState.toLowerCase();
    if (!["none", "null", "inactive", "disabled"].includes(lowered)) {
      return true;
    }
  }
  return record.derived?.governance?.downgraded === true;
}

function isOverrideApplied(record: NormalizedExecutionRecord): boolean {
  if (record.derived?.runtimeDecision?.forced) {
    return true;
  }
  const reason = reasonOf(record)?.toLowerCase() ?? "";
  return reason.includes("override") || reason.includes("manual");
}

function detectKinds(record: NormalizedExecutionRecord): RolloutAnomalyKind[] {
  const kinds: RolloutAnomalyKind[] = [];
  if (isDefaultPolicy(record)) {
    kinds.push("default_policy");
  }
  if (isConservativeDefault(record)) {
    kinds.push("conservative_default");
  }
  if (isFailed(record)) {
    kinds.push("failed");
  }
  if (isRollbackApplied(record)) {
    kinds.push("rollback_applied");
  }
  if (isOverrideApplied(record)) {
    kinds.push("override_applied");
  }
  return kinds;
}

export function aggregateRolloutAnomalies(
  records: readonly NormalizedExecutionRecord[],
  recentLimit = DEFAULT_RECENT_LIMIT,
): RolloutAnomalyAggregate {
  const counts = {
    defaultPolicy: 0,
    conservativeDefault: 0,
    failed: 0,
    rollbackApplied: 0,
    overrideApplied: 0,
  };

  const recentCandidates: RolloutAnomalySliceItem[] = [];

  for (const record of records) {
    const kinds = detectKinds(record);
    if (kinds.length === 0) {
      continue;
    }

    if (kinds.includes("default_policy")) {
      counts.defaultPolicy += 1;
    }
    if (kinds.includes("conservative_default")) {
      counts.conservativeDefault += 1;
    }
    if (kinds.includes("failed")) {
      counts.failed += 1;
    }
    if (kinds.includes("rollback_applied")) {
      counts.rollbackApplied += 1;
    }
    if (kinds.includes("override_applied")) {
      counts.overrideApplied += 1;
    }

    recentCandidates.push({
      recordId: record.id,
      route: routeNameOf(record),
      receivedAt: record.receivedAt,
      kinds,
      reason: reasonOf(record),
      stateSource:
        record.derived?.governance?.stateSource ??
        asString(
          pickNested(record.raw as RolloutRawRecord, [
            "runtime_v2_route_meta",
            "execution_report",
            "governance",
            "state_source",
          ]),
        ),
      promotionState:
        record.derived?.governance?.promotionState ??
        asString(
          pickNested(record.raw as RolloutRawRecord, [
            "runtime_v2_route_meta",
            "execution_report",
            "governance",
            "promotion_state",
          ]),
        ),
    });
  }

  const safeLimit = Number.isFinite(recentLimit) ? Math.max(0, Math.trunc(recentLimit)) : DEFAULT_RECENT_LIMIT;
  const recent = recentCandidates
    .sort((a, b) => {
      const timeDiff = toMillis(b.receivedAt) - toMillis(a.receivedAt);
      if (timeDiff !== 0) {
        return timeDiff;
      }
      return b.recordId.localeCompare(a.recordId);
    })
    .slice(0, safeLimit);

  return { counts, recent };
}
