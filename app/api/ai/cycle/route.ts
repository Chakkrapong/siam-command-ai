import { NextResponse } from "next/server";
import { isDeveloperEmail } from "@/lib/server/access";
import { getAuthenticatedUser } from "@/lib/server/session";
import { logAiUsage, logCommand } from "@/lib/server/persistence";
import { runAutoCycle } from "@/lib/server/autoCompany";
import { setAgentStatus } from "@/lib/server/agent-status";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const payload = (await request.json()) as {
      command?: string;
      project?: string;
      phase?: string;
    };

    const command = payload.command?.trim();

    if (!command) {
      return NextResponse.json({ error: "Command is required" }, { status: 400 });
    }

    const result = await runAutoCycle({
      project: payload.project?.trim() || "SC-AIC Prime",
      phase: payload.phase?.trim() || "Phase 1 - Core MVP",
      tech: ["Next.js", "Supabase", "Stripe"],
      goal: command,
    });

    const creditsUsed = 3;
    const isDev = isDeveloperEmail(user.email);

    await logAiUsage({
      userId: user.id,
      model: result.model,
      prompt: command,
      output: result.deployed,
      creditsUsed,
      skipCreditDecrement: isDev,
    });

    await logCommand({
      userId: user.id,
      commandType: "ai.cycle",
      prompt: command,
      output: result.deployed,
      status: "success",
      metadata: {
        project: payload.project?.trim() || "SC-AIC Prime",
        phase: payload.phase?.trim() || "Phase 1 - Core MVP",
        creditsUsed,
        model: result.model,
      },
    });

    return NextResponse.json({
      result,
      creditsUsed: isDev ? 0 : creditsUsed,
    });
  } catch (error) {
    await setAgentStatus("jarvis-core", "error");

    await logCommand({
      userId: user.id,
      commandType: "ai.cycle",
      prompt: "AI cycle failed before prompt persistence",
      status: "error",
      metadata: {
        message: error instanceof Error ? error.message : "Unknown AI cycle error",
      },
    });

    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "AI cycle failed unexpectedly",
      },
      { status: 500 },
    );
  }
}
