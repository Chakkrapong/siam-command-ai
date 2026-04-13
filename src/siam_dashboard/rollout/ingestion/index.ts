import type { RolloutDashboardConfig } from "../config";
import type {
  RolloutQuery,
  RolloutQueryResult,
  RolloutSourceType,
} from "../types";

export type RolloutRawExecutionRecord = Record<string, unknown>;

export interface IngestionPullState {
  cursor?: string;
  since?: string;
}

export interface IngestionPullResult {
  records: RolloutRawExecutionRecord[];
  cursor?: string;
  hasMore: boolean;
  malformedLineCount?: number;
}

export interface IngestionHealthStatus {
  ok: boolean;
  checkedAt: string;
  details?: string;
}

export interface IngestionAdapterContext {
  sourceId: string;
  sourceType: RolloutSourceType;
  config: RolloutDashboardConfig;
  now: () => Date;
  signal?: AbortSignal;
}

export interface RolloutIngestionAdapter {
  readonly sourceType: RolloutSourceType;
  pull(
    state: IngestionPullState | undefined,
    context: IngestionAdapterContext,
  ): Promise<IngestionPullResult>;
  query?(query: RolloutQuery, context: IngestionAdapterContext): Promise<RolloutQueryResult>;
  healthCheck?(context: IngestionAdapterContext): Promise<IngestionHealthStatus>;
}

export interface RolloutAdapterRegistry {
  register(adapter: RolloutIngestionAdapter): void;
  get(sourceType: RolloutSourceType): RolloutIngestionAdapter | undefined;
  has(sourceType: RolloutSourceType): boolean;
  list(): RolloutIngestionAdapter[];
}

export function createRolloutAdapterRegistry(
  initialAdapters: readonly RolloutIngestionAdapter[] = [],
): RolloutAdapterRegistry {
  const bySourceType = new Map<RolloutSourceType, RolloutIngestionAdapter>();
  for (const adapter of initialAdapters) {
    bySourceType.set(adapter.sourceType, adapter);
  }

  return {
    register(adapter: RolloutIngestionAdapter): void {
      bySourceType.set(adapter.sourceType, adapter);
    },
    get(sourceType: RolloutSourceType): RolloutIngestionAdapter | undefined {
      return bySourceType.get(sourceType);
    },
    has(sourceType: RolloutSourceType): boolean {
      return bySourceType.has(sourceType);
    },
    list(): RolloutIngestionAdapter[] {
      return Array.from(bySourceType.values());
    },
  };
}

export { createJsonlRolloutIngestionAdapter, resolveExecutionLogJsonlPath } from "./jsonl";
