import { getRedisClient } from "@/lib/server/redis";

type MemoryItem = {
  agent: string;
  payload: string;
  createdAt: string;
};

const fallbackMemory = new Map<string, MemoryItem[]>();

const keyFor = (agent: string): string => `scaic:agent-memory:${agent}`;

export async function pushAgentMemory(agent: string, payload: string): Promise<void> {
  const item: MemoryItem = {
    agent,
    payload,
    createdAt: new Date().toISOString(),
  };

  const redis = await getRedisClient();

  if (redis) {
    const key = keyFor(agent);
    await redis.rPush(key, JSON.stringify(item));
    await redis.lTrim(key, -50, -1);
    return;
  }

  const existing = fallbackMemory.get(agent) ?? [];
  existing.push(item);
  fallbackMemory.set(agent, existing.slice(-50));
}

export async function getAgentMemory(agent: string, limit = 5): Promise<MemoryItem[]> {
  const redis = await getRedisClient();

  if (redis) {
    const key = keyFor(agent);
    const raw = await redis.lRange(key, -limit, -1);
    return raw
      .map((entry: string) => {
        try {
          return JSON.parse(entry) as MemoryItem;
        } catch {
          return null;
        }
      })
      .filter((entry: MemoryItem | null): entry is MemoryItem => Boolean(entry));
  }

  const items = fallbackMemory.get(agent) ?? [];
  return items.slice(-limit);
}
