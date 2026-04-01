const requiredEnvNames = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "STRIPE_SECRET_KEY",
  "STRIPE_PRICE_ID",
  "OPENAI_API_KEY",
] as const;

type RequiredEnvName = (typeof requiredEnvNames)[number];

export function getEnv(name: RequiredEnvName): string {
  const value = process.env[name];

  if (!requiredEnvNames.includes(name)) {
    throw new Error(`Unsupported environment variable: ${name}`);
  }

  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}

export function getOptionalEnv(name: string): string | undefined {
  return process.env[name];
}
