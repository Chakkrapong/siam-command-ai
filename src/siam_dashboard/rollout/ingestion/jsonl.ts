import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import { isAbsolute, resolve } from "node:path";

import type {
  IngestionAdapterContext,
  IngestionPullResult,
  IngestionPullState,
  RolloutIngestionAdapter,
  RolloutRawExecutionRecord,
} from "./index";

const DEFAULT_EXECUTION_LOG_JSONL_PATH = ".siam/execution-log.jsonl";
const EXECUTION_LOG_ENV_KEY = "SIAM_EXECUTION_LOG_JSONL_PATH";
const CURSOR_PREFIX = "line:";

function isObjectRecord(value: unknown): value is RolloutRawExecutionRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseCursorLine(cursor: string | undefined): number {
  if (!cursor) {
    return 0;
  }
  if (!cursor.startsWith(CURSOR_PREFIX)) {
    return 0;
  }
  const parsed = Number.parseInt(cursor.slice(CURSOR_PREFIX.length), 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return parsed;
}

export function resolveExecutionLogJsonlPath(env: NodeJS.ProcessEnv = process.env): string {
  const configured = env[EXECUTION_LOG_ENV_KEY]?.trim();
  if (configured) {
    return isAbsolute(configured) ? configured : resolve(process.cwd(), configured);
  }
  return resolve(process.cwd(), DEFAULT_EXECUTION_LOG_JSONL_PATH);
}

export function createJsonlRolloutIngestionAdapter(
  env: NodeJS.ProcessEnv = process.env,
): RolloutIngestionAdapter {
  return {
    sourceType: "jsonl",
    async pull(state: IngestionPullState | undefined, context: IngestionAdapterContext): Promise<IngestionPullResult> {
      const filePath = resolveExecutionLogJsonlPath(env);
      try {
        await stat(filePath);
      } catch {
        return {
          records: [],
          hasMore: false,
          cursor: state?.cursor,
          malformedLineCount: 0,
        };
      }

      const startLine = parseCursorLine(state?.cursor);
      const maxRecords = Math.max(1, context.config.ingestion.maxRecordsPerPoll);
      const records: RolloutRawExecutionRecord[] = [];
      let malformedLineCount = 0;
      let lineNumber = 0;
      let nextCursor = state?.cursor;
      let hasMore = false;

      const stream = createReadStream(filePath, { encoding: "utf8" });
      const reader = createInterface({
        input: stream,
        crlfDelay: Number.POSITIVE_INFINITY,
      });

      try {
        for await (const line of reader) {
          if (context.signal?.aborted) {
            throw new Error("jsonl ingestion aborted");
          }

          lineNumber += 1;
          if (lineNumber <= startLine) {
            continue;
          }

          const trimmed = line.trim();
          if (!trimmed) {
            nextCursor = `${CURSOR_PREFIX}${lineNumber}`;
            continue;
          }

          let parsed: unknown;
          try {
            parsed = JSON.parse(trimmed);
          } catch {
            malformedLineCount += 1;
            nextCursor = `${CURSOR_PREFIX}${lineNumber}`;
            continue;
          }

          if (!isObjectRecord(parsed)) {
            malformedLineCount += 1;
            nextCursor = `${CURSOR_PREFIX}${lineNumber}`;
            continue;
          }

          records.push(parsed);
          nextCursor = `${CURSOR_PREFIX}${lineNumber}`;

          if (records.length >= maxRecords) {
            hasMore = true;
            break;
          }
        }
      } finally {
        reader.close();
        stream.destroy();
      }

      return {
        records,
        cursor: nextCursor,
        hasMore,
        malformedLineCount,
      };
    },
  };
}
