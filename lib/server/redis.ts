import { createClient } from "redis";
import { getOptionalEnv } from "@/lib/env";

type RedisClient = ReturnType<typeof createClient>;

let client: RedisClient | null = null;
let connectPromise: Promise<RedisClient | null> | null = null;

export async function getRedisClient(): Promise<RedisClient | null> {
  const url = getOptionalEnv("REDIS_URL");

  if (!url) {
    return null;
  }

  if (client) {
    return client;
  }

  if (connectPromise) {
    return connectPromise;
  }

  connectPromise = (async () => {
    const nextClient = createClient({ url });
    nextClient.on("error", () => {
      // Keep runtime resilient; callers handle null/failed operations gracefully.
    });

    await nextClient.connect();
    client = nextClient;
    return client;
  })().catch(() => null);

  return connectPromise;
}

export async function closeRedisClient(): Promise<void> {
  if (client?.isOpen) {
    await client.quit();
  }
  client = null;
  connectPromise = null;
}
