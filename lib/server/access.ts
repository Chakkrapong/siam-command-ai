import { getOptionalEnv } from "@/lib/env";

const defaultDeveloperEmails = ["jpflightcase@gmail.com"];

function getDeveloperEmails() {
  const configured = getOptionalEnv("DEV_ADMIN_EMAILS");

  if (!configured) {
    return defaultDeveloperEmails;
  }

  return configured
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
}

export function isDeveloperEmail(email: string | null | undefined) {
  if (!email) {
    return false;
  }

  return getDeveloperEmails().includes(email.trim().toLowerCase());
}

export function getEffectiveAccess(input: {
  email: string | null | undefined;
  plan?: string | null;
  aiCredits?: number | null;
}) {
  const isDev = isDeveloperEmail(input.email);

  if (isDev) {
    return {
      isDev: true,
      role: "dev",
      plan: "dev",
      aiCredits: 999999,
    } as const;
  }

  return {
    isDev: false,
    role: "user",
    plan: input.plan ?? "free",
    aiCredits: input.aiCredits ?? 0,
  } as const;
}