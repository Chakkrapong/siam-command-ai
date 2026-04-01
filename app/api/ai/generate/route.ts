import { NextResponse } from "next/server";
import OpenAI from "openai";
import { getEnv, getOptionalEnv } from "@/lib/env";
import { isDeveloperEmail } from "@/lib/server/access";
import { getAuthenticatedUser } from "@/lib/server/session";
import { logAiUsage, logCommand } from "@/lib/server/persistence";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { prompt } = (await request.json()) as { prompt?: string };

    if (!prompt || !prompt.trim()) {
      return NextResponse.json({ error: "Prompt is required" }, { status: 400 });
    }

    const openai = new OpenAI({ apiKey: getEnv("OPENAI_API_KEY") });
    const model = getOptionalEnv("OPENAI_MODEL") ?? "gpt-4.1-mini";

    const response = await openai.responses.create({
      model,
      input: [
        {
          role: "system",
          content:
            "You are Siam Command AI assistant. Provide concise, actionable responses for business automation.",
        },
        {
          role: "user",
          content: prompt,
        },
      ],
    });

    const output = response.output_text || "";
    const creditsUsed = 1;
    const isDev = isDeveloperEmail(user.email);

    await logAiUsage({
      userId: user.id,
      model,
      prompt,
      output,
      creditsUsed,
      skipCreditDecrement: isDev,
    });

    await logCommand({
      userId: user.id,
      commandType: "ai.generate",
      prompt,
      output,
      status: "success",
      metadata: {
        model,
        creditsUsed,
      },
    });

    return NextResponse.json({
      output,
      model,
      creditsUsed: isDev ? 0 : creditsUsed,
      role: isDev ? "dev" : "user",
    });
  } catch (error) {
    await logCommand({
      userId: user.id,
      commandType: "ai.generate",
      prompt: "AI generation failed before prompt persistence",
      status: "error",
      metadata: {
        message: error instanceof Error ? error.message : "Unknown AI error",
      },
    });

    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "AI generation failed unexpectedly",
      },
      { status: 500 },
    );
  }
}
