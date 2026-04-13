import type {
  ExecutionActor,
  ExecutionErrorInfo,
  ExecutionMetrics,
  ExecutionStatus,
  GovernanceSnapshot,
  NormalizedExecutionRecord,
  RolloutRawRecord,
  RolloutSourceType,
  RuntimeDecisionSnapshot,
  SeverityLevel,
  ShadowSnapshot,
} from "../types";

export interface ExecutionRecordNormalizationContext {
  sourceType: RolloutSourceType;
  sourceRef: string;
  sourceOffset?: string | number;
  sourceIngestedAt?: string;
  receivedAt?: string;
  service?: string;
  environment?: string;
  region?: string;
  workflowVersion?: string;
  runbookId?: string;
}

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

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return undefined;
}

function asInteger(value: unknown): number | undefined {
  const parsed = asNumber(value);
  if (parsed === undefined) {
    return undefined;
  }
  return Math.trunc(parsed);
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
    if (lowered === "true" || lowered === "1" || lowered === "yes") {
      return true;
    }
    if (lowered === "false" || lowered === "0" || lowered === "no") {
      return false;
    }
  }
  return undefined;
}

function toIsoTimestamp(value: unknown, fallback: string): string {
  const text = asString(value);
  if (!text) {
    return fallback;
  }
  const parsed = Date.parse(text);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return new Date(parsed).toISOString();
}

function pickNested(raw: Record<string, unknown>, ...paths: ReadonlyArray<ReadonlyArray<string>>): unknown {
  for (const path of paths) {
    let current: unknown = raw;
    let missing = false;
    for (const key of path) {
      const currentRecord = asRecord(current);
      if (!currentRecord || !(key in currentRecord)) {
        missing = true;
        break;
      }
      current = currentRecord[key];
    }
    if (!missing && current !== undefined) {
      return current;
    }
  }
  return undefined;
}

function compact<T extends Record<string, unknown>>(value: T): T | undefined {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  if (entries.length === 0) {
    return undefined;
  }
  return Object.fromEntries(entries) as T;
}

function normalizeStatus(raw: Record<string, unknown>, runtimeDecision: RuntimeDecisionSnapshot | undefined): ExecutionStatus {
  const blocked = asBoolean(raw.blocked) ?? false;
  if (blocked || runtimeDecision?.guardBlocked) {
    return "canceled";
  }
  const stopReason = (asString(raw.stop_reason) ?? "").toLowerCase();
  if (["completed", "complete", "ok", "success", "succeeded"].includes(stopReason)) {
    return "succeeded";
  }
  if (["queued", "pending", "scheduled"].includes(stopReason)) {
    return "queued";
  }
  if (["running", "in_progress", "streaming"].includes(stopReason)) {
    return "running";
  }
  if (["timed_out", "timeout", "deadline_exceeded"].includes(stopReason)) {
    return "timed_out";
  }
  if (["canceled", "cancelled", "aborted", "blocked"].includes(stopReason)) {
    return "canceled";
  }
  if (["failed", "error", "exception", "tool_error"].includes(stopReason)) {
    return "failed";
  }
  return "succeeded";
}

function normalizeSeverity(
  status: ExecutionStatus,
  error: ExecutionErrorInfo | undefined,
  runtimeDecision: RuntimeDecisionSnapshot | undefined,
  shadow: ShadowSnapshot | undefined,
): SeverityLevel {
  if (status === "failed" || status === "timed_out" || error) {
    return "error";
  }
  if (status === "canceled" || runtimeDecision?.guardBlocked || shadow?.event === "shadow_diff") {
    return "warning";
  }
  if (shadow?.event === "shadow_error") {
    return "critical";
  }
  return "info";
}

function buildMetrics(raw: Record<string, unknown>): ExecutionMetrics | undefined {
  return compact<ExecutionMetrics>({
    queueLatencyMs: asNumber(pickNested(raw, ["queue_latency_ms"])),
    runDurationMs: asNumber(
      pickNested(raw, ["run_duration_ms"], ["duration_ms"], ["latency_ms"], ["runtime_duration_ms"]),
    ),
    totalDurationMs: asNumber(pickNested(raw, ["total_duration_ms"])),
    retries: asInteger(pickNested(raw, ["retry_count"], ["retries"])),
    cpuPct: asNumber(pickNested(raw, ["cpu_pct"])),
    memoryMb: asNumber(pickNested(raw, ["memory_mb"])),
  });
}

function buildError(raw: Record<string, unknown>): ExecutionErrorInfo | undefined {
  const fromObject = asRecord(pickNested(raw, ["error"]));
  const code = asString(fromObject?.code) ?? asString(pickNested(raw, ["error_code"]));
  const message =
    asString(fromObject?.message) ??
    asString(pickNested(raw, ["error_message"], ["runtime_v2_route_meta", "runtime_execution", "validation_reason"]));
  if (!code && !message) {
    return undefined;
  }
  return {
    code: code ?? "execution_error",
    message: message ?? "Execution error",
    details: asString(fromObject?.details) ?? asString(pickNested(raw, ["error_details"])),
    retryable: asBoolean(fromObject?.retryable) ?? asBoolean(pickNested(raw, ["retryable"])),
  };
}

function buildActor(raw: Record<string, unknown>): ExecutionActor {
  const actor = asRecord(raw.actor);
  const actorId =
    asString(actor?.id) ??
    asString(pickNested(raw, ["operator_id"], ["user_id"], ["session_id"])) ??
    "system";
  const actorTypeRaw = (asString(actor?.type) ?? "system").toLowerCase();
  const actorType: ExecutionActor["type"] =
    actorTypeRaw === "operator" || actorTypeRaw === "service_account" ? actorTypeRaw : "system";

  return {
    id: actorId,
    type: actorType,
    displayName: asString(actor?.displayName) ?? asString(actor?.display_name),
  };
}

function buildRuntimeDecision(raw: Record<string, unknown>): RuntimeDecisionSnapshot | undefined {
  const runtimeDecision =
    asRecord(pickNested(raw, ["runtime_decision"])) ??
    asRecord(pickNested(raw, ["runtime_v2_route_meta", "runtime_decision"])) ??
    asRecord(pickNested(raw, ["decision_trace", "runtime_decision"]));

  if (!runtimeDecision) {
    return undefined;
  }

  return compact<RuntimeDecisionSnapshot>({
    routeName: asString(runtimeDecision.route_name),
    selectedRuntime: asString(runtimeDecision.selected_runtime),
    primaryRuntime: asString(runtimeDecision.primary_runtime),
    reason: asString(runtimeDecision.reason),
    partialEnabled: asBoolean(runtimeDecision.partial_enabled),
    allowlisted: asBoolean(runtimeDecision.allowlisted),
    inRollout: asBoolean(runtimeDecision.in_rollout),
    guardBlocked: asBoolean(runtimeDecision.guard_blocked),
    guardReason: asString(runtimeDecision.guard_reason),
    riskLevel: asString(runtimeDecision.risk_level),
    riskReason: asString(runtimeDecision.risk_reason),
    rolloutPercent: asNumber(runtimeDecision.rollout_percent),
    rolloutBucket: asInteger(runtimeDecision.rollout_bucket),
    sampled: asBoolean(runtimeDecision.sampled),
    forced: asBoolean(runtimeDecision.forced),
    autoDisabled: asBoolean(runtimeDecision.auto_disabled),
  });
}

function buildGovernance(raw: Record<string, unknown>): GovernanceSnapshot | undefined {
  const governance =
    asRecord(pickNested(raw, ["execution_report", "governance"])) ??
    asRecord(pickNested(raw, ["runtime_v2_route_meta", "execution_report", "governance"])) ??
    asRecord(pickNested(raw, ["decision_trace", "execution_report", "governance"]));

  if (!governance) {
    return undefined;
  }

  return compact<GovernanceSnapshot>({
    promotionState: asString(governance.promotion_state),
    routeFamily: asString(governance.route_family),
    stateSource: asString(governance.state_source),
    downgraded: asBoolean(governance.downgraded),
    downgradeReason: asString(governance.downgrade_reason),
    rollbackState: asString(governance.rollback_state),
  });
}

function toTags(values: ReadonlyArray<string | undefined>): string[] {
  return Array.from(new Set(values.filter((item): item is string => Boolean(item)).map((item) => item.toLowerCase())));
}

export function normalizeExecutionRecord(
  rawRecord: RolloutRawRecord,
  context: ExecutionRecordNormalizationContext,
): NormalizedExecutionRecord {
  const raw = asRecord(rawRecord) ?? {};
  const nowIso = new Date().toISOString();

  const runtimeDecision = buildRuntimeDecision(raw);
  const governance = buildGovernance(raw);
  const routeMeta = asRecord(pickNested(raw, ["runtime_v2_route_meta"]));
  const decisionTrace = asRecord(pickNested(raw, ["decision_trace"]));
  const shadowMeta = asRecord(pickNested(raw, ["shadow_meta"]));
  const error = buildError(raw);

  const startedAt = toIsoTimestamp(
    pickNested(raw, ["started_at"], ["start_time"], ["timestamp"], ["created_at"]),
    context.sourceIngestedAt ?? nowIso,
  );
  const endedAt = asString(pickNested(raw, ["ended_at"], ["completed_at"], ["finished_at"]));
  const endedAtIso = endedAt ? toIsoTimestamp(endedAt, startedAt) : undefined;
  const sourceIngestedAt = toIsoTimestamp(context.sourceIngestedAt, nowIso);
  const receivedAt = toIsoTimestamp(
    pickNested(raw, ["received_at"], ["ingested_at"], ["timestamp"], ["created_at"]) ?? context.receivedAt,
    sourceIngestedAt,
  );

  const shadow: ShadowSnapshot | undefined = compact<ShadowSnapshot>({
    event: asString(pickNested(raw, ["shadow_event"])) ?? asString(shadowMeta?.shadow_event),
    reason: asString(shadowMeta?.reason),
    match: asBoolean(shadowMeta?.match),
    errorKind: asString(shadowMeta?.error_kind),
  });

  const derived = compact({
    runtimeDecision,
    governance,
    decisionTrace: compact({
      selectedCommand: asString(pickNested(raw, ["selected_command"], ["decision_trace", "selected_command"])),
      selectedTool: asString(pickNested(raw, ["selected_tool"], ["decision_trace", "selected_tool"])),
      policyName: asString(pickNested(raw, ["policy_name"], ["decision_trace", "policy_name"])),
      reason: asString(pickNested(raw, ["decision_trace", "reason"])),
    }),
    routeMeta: compact({
      event: asString(pickNested(raw, ["runtime_v2_route_event"])),
      routeName: asString(routeMeta?.route_name),
      commandName: asString(routeMeta?.command_name),
      reason: asString(routeMeta?.reason),
    }),
    shadow,
  });

  const status = normalizeStatus(raw, runtimeDecision);
  const severity = normalizeSeverity(status, error, runtimeDecision, shadow);

  const workflowId =
    asString(pickNested(raw, ["workflow_id"])) ??
    runtimeDecision?.routeName ??
    asString(routeMeta?.route_name) ??
    asString(pickNested(raw, ["selected_command"])) ??
    "unknown_workflow";

  const recordId =
    asString(pickNested(raw, ["id"], ["execution_id"], ["request_id"], ["trace_id"])) ??
    `${context.sourceRef}:${String(context.sourceOffset ?? asString(pickNested(raw, ["timestamp"])) ?? "unknown")}`;

  return {
    id: recordId,
    workflowId,
    workflowVersion:
      context.workflowVersion ??
      asString(pickNested(raw, ["workflow_version"], ["runtime_v2_route_meta", "version"])),
    rolloutId:
      asString(pickNested(raw, ["rollout_id"], ["session_id"])) ??
      `${workflowId}:${new Date(startedAt).toISOString().slice(0, 10)}`,
    runbookId: context.runbookId ?? asString(pickNested(raw, ["runbook_id"])),
    environment:
      asString(pickNested(raw, ["environment"], ["env"], ["deployment", "environment"])) ??
      context.environment ??
      "unknown",
    service: asString(pickNested(raw, ["service"], ["service_name"])) ?? context.service ?? "siam-command-ai-center",
    region: asString(pickNested(raw, ["region"], ["deployment", "region"])) ?? context.region,
    startedAt,
    endedAt: endedAtIso,
    receivedAt,
    status,
    severity,
    actor: buildActor(raw),
    tags: toTags([
      asString(pickNested(raw, ["policy_name"])),
      runtimeDecision?.riskLevel,
      runtimeDecision?.riskReason,
      asString(pickNested(raw, ["runtime_v2_route_event"])),
      shadow?.event,
      shadow?.reason,
      status,
    ]),
    metrics: buildMetrics(raw),
    error,
    sourceType: context.sourceType,
    sourceRef: context.sourceRef,
    sourceOffset: context.sourceOffset,
    sourceIngestedAt,
    derived,
    raw,
  };
}

export function normalizeExecutionRecords(
  rawRecords: readonly RolloutRawRecord[],
  context: Omit<ExecutionRecordNormalizationContext, "sourceOffset"> & { startOffset?: number },
): NormalizedExecutionRecord[] {
  const startOffset = context.startOffset ?? 0;
  return rawRecords.map((rawRecord, index) =>
    normalizeExecutionRecord(rawRecord, {
      ...context,
      sourceOffset: startOffset + index,
    }),
  );
}
