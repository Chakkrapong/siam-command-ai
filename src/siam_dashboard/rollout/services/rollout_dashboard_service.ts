import { aggregateRolloutAnomalies } from "../aggregate/anomalies";
import { aggregateRolloutMetrics } from "../aggregate/metrics";
import { scoreRolloutReadiness } from "../aggregate/readiness";
import { aggregateRouteSummary } from "../aggregate/route_summary";
import { resolveRolloutDashboardConfig, type RolloutDashboardConfig } from "../config";
import {
  createJsonlRolloutIngestionAdapter,
  createRolloutAdapterRegistry,
  resolveExecutionLogJsonlPath,
  type RolloutIngestionAdapter,
} from "../ingestion";
import { normalizeExecutionRecords } from "../normalize/execution_record";
import type {
  RolloutDashboardLoadRequest,
  RolloutDashboardServiceContract,
  RolloutDashboardViewModel,
  RolloutRawRecord,
  RolloutSourceType,
} from "../types";

const LINE_CURSOR_PREFIX = "line:";

export interface RolloutDashboardServiceOptions {
  config?: Partial<RolloutDashboardConfig>;
  adapters?: readonly RolloutIngestionAdapter[];
  now?: () => Date;
}

function parseCursorOffset(cursor: string | undefined): number {
  if (!cursor || !cursor.startsWith(LINE_CURSOR_PREFIX)) {
    return 0;
  }
  const parsed = Number.parseInt(cursor.slice(LINE_CURSOR_PREFIX.length), 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return parsed;
}

function resolveSourceRef(sourceType: RolloutSourceType, sourceId: string | undefined): string {
  if (sourceId && sourceId.trim().length > 0) {
    return sourceId.trim();
  }
  if (sourceType === "jsonl") {
    return resolveExecutionLogJsonlPath();
  }
  return `${sourceType}:default`;
}

export class RolloutDashboardService implements RolloutDashboardServiceContract {
  private readonly config: RolloutDashboardConfig;
  private readonly registry: ReturnType<typeof createRolloutAdapterRegistry>;
  private readonly now: () => Date;

  constructor(options: RolloutDashboardServiceOptions = {}) {
    this.config = resolveRolloutDashboardConfig(options.config ?? {});
    this.now = options.now ?? (() => new Date());
    this.registry = createRolloutAdapterRegistry([
      createJsonlRolloutIngestionAdapter(),
      ...(options.adapters ?? []),
    ]);
  }

  async loadViewModel(request: RolloutDashboardLoadRequest = {}): Promise<RolloutDashboardViewModel> {
    const sourceType = this.resolveSourceType(request.sourceType);
    const adapter = this.registry.get(sourceType);
    if (!adapter) {
      throw new Error(`rollout dashboard adapter missing for source type: ${sourceType}`);
    }

    const generatedAt = this.now().toISOString();
    const sourceRef = resolveSourceRef(sourceType, request.sourceId);
    const pullResult = await adapter.pull(
      { cursor: request.cursor },
      {
        sourceId: sourceRef,
        sourceType,
        config: this.config,
        now: this.now,
        signal: request.signal,
      },
    );

    const rawRecords = pullResult.records as RolloutRawRecord[];
    const records = normalizeExecutionRecords(rawRecords, {
      sourceType,
      sourceRef,
      sourceIngestedAt: generatedAt,
      receivedAt: generatedAt,
      startOffset: parseCursorOffset(request.cursor),
    });

    const metrics = aggregateRolloutMetrics(records);
    const routeSummary = aggregateRouteSummary(records);
    const anomalies = aggregateRolloutAnomalies(records);
    const readiness = scoreRolloutReadiness(metrics, anomalies, this.config.readiness);

    return {
      generatedAt,
      ingestion: {
        sourceType,
        sourceRef,
        nextCursor: pullResult.cursor,
        hasMore: pullResult.hasMore,
        malformedLineCount: pullResult.malformedLineCount ?? 0,
      },
      records,
      metrics,
      routeSummary,
      anomalies,
      readiness,
    };
  }

  private resolveSourceType(requestedSourceType: RolloutSourceType | undefined): RolloutSourceType {
    if (requestedSourceType) {
      if (!this.registry.has(requestedSourceType)) {
        throw new Error(`rollout dashboard adapter unavailable for requested source: ${requestedSourceType}`);
      }
      return requestedSourceType;
    }

    for (const sourceType of this.config.enabledSources) {
      if (this.registry.has(sourceType)) {
        return sourceType;
      }
    }

    const fallback = this.registry.list()[0];
    if (!fallback) {
      throw new Error("rollout dashboard has no registered ingestion adapters");
    }
    return fallback.sourceType;
  }
}

export function createRolloutDashboardService(
  options: RolloutDashboardServiceOptions = {},
): RolloutDashboardServiceContract {
  return new RolloutDashboardService(options);
}
