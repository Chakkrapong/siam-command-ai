import OpenAI from "openai";
import { getEnv, getOptionalEnv } from "@/lib/env";
import { pushAgentMemory } from "@/lib/server/agent-memory";
import { setAgentStatus } from "@/lib/server/agent-status";

export type AgentContext = {
  project: string;
  phase: string;
  goal: string;
  tech?: string[];
};

export type AutoCycleResult = {
  idea: string;
  built: string;
  fixed: string;
  growth: string;
  deployed: string;
  model: string;
};

const buildAgentPrompt = (role: string, context: AgentContext): string => `
You are ${role} AI.

Project: ${context.project}
Phase: ${context.phase}
Goal: ${context.goal}
Tech: ${(context.tech ?? []).join(", ")}

Rules:
- Think step-by-step
- Be autonomous
- Keep outputs concise and implementation-ready
`;

const runAgent = async (input: {
  role: string;
  task: string;
  context: AgentContext;
  model: string;
}): Promise<string> => {
  const openai = new OpenAI({ apiKey: getEnv("OPENAI_API_KEY") });

  const response = await openai.responses.create({
    model: input.model,
    input: [
      {
        role: "system",
        content: buildAgentPrompt(input.role, input.context),
      },
      {
        role: "user",
        content: input.task,
      },
    ],
  });

  return response.output_text || "No output";
};

export async function runAutoCycle(context: AgentContext): Promise<AutoCycleResult> {
  const model = getOptionalEnv("OPENAI_MODEL") ?? "gpt-4.1-mini";

  await setAgentStatus("jarvis-core", "running");

  await setAgentStatus("builder", "idle");
  await setAgentStatus("debugger", "idle");
  await setAgentStatus("growth", "idle");
  await setAgentStatus("deployer", "idle");

  const idea = await runAgent({
    role: "Product Strategist",
    task: "Decide next feature that maximizes growth and revenue. Return a short actionable roadmap.",
    context,
    model,
  });
  await pushAgentMemory("jarvis-core", idea);

  await setAgentStatus("builder", "running");
  const built = await runAgent({
    role: "Builder Engineer",
    task: `Build implementation plan and code patch summary for this feature:\n\n${idea}`,
    context,
    model,
  });
  await pushAgentMemory("builder", built);
  await setAgentStatus("builder", "success");

  await setAgentStatus("debugger", "running");
  const fixed = await runAgent({
    role: "Debugger Engineer",
    task: `Find risks/bugs and provide corrected version for:\n\n${built}`,
    context,
    model,
  });
  await pushAgentMemory("debugger", fixed);
  await setAgentStatus("debugger", "success");

  await setAgentStatus("growth", "running");
  const growth = await runAgent({
    role: "Growth Strategist",
    task: `Optimize this for activation, retention, and revenue:\n\n${fixed}`,
    context,
    model,
  });
  await pushAgentMemory("growth", growth);
  await setAgentStatus("growth", "success");

  await setAgentStatus("deployer", "running");
  const deployed = `[DEPLOYED]\n${growth.substring(0, 500)}...`;
  await pushAgentMemory("deployer", deployed);
  await setAgentStatus("deployer", "success");
  await setAgentStatus("jarvis-core", "success");

  return {
    idea,
    built,
    fixed,
    growth,
    deployed,
    model,
  };
}
