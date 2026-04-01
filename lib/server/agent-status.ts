import { getRedisClient } from "@/lib/server/redis";

export type AgentStatus = {
  name: string;
  status: "idle" | "running" | "success" | "error";
  updatedAt: string;
};

const AGENTS = ["jarvis-core", "builder", "debugger", "growth", "deployer"] as const;
const fallbackStatus = new Map<string, AgentStatus>();

const statusKey = (name: string): string => `scaic:agent-status:${name}`;

export async function setAgentStatus(
  name: string,
  status: AgentStatus["status"],
): Promise<void> {
  const updatedAt = new Date().toISOString();
  const payload: AgentStatus = { name, status, updatedAt };

  const redis = await getRedisClient();

  if (redis) {
    await redis.set(statusKey(name), JSON.stringify(payload));
    return;
  }

  fallbackStatus.set(name, payload);
}

export async function getAllAgentStatuses(): Promise<AgentStatus[]> {
  const redis = await getRedisClient();

  if (redis) {
    const statuses = await Promise.all(
      AGENTS.map(async (name) => {
        const raw = await redis.get(statusKey(name));

        if (!raw) {
          return {
            name,
            status: "idle",
            updatedAt: new Date(0).toISOString(),
          } as AgentStatus;
        }

        try {
          return JSON.parse(raw) as AgentStatus;
        } catch {
          return {
            name,
            status: "idle",
            updatedAt: new Date(0).toISOString(),
          } as AgentStatus;
        }
      }),
    );

    return statuses;
  }

  return AGENTS.map((name) =>
    fallbackStatus.get(name) ?? {
      name,
      status: "idle",
      updatedAt: new Date(0).toISOString(),
    },
  );
}
