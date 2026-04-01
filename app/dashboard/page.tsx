"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type UserData = {
  id: string;
  email: string | null;
  fullName: string | null;
  role: string;
  isDev: boolean;
  plan: string;
  aiCredits: number;
};

type SubscriptionData = {
  status: string;
  stripe_price_id: string | null;
  current_period_end: string | null;
} | null;

type CommandLog = {
  id: string;
  command_type: string;
  status: string;
  prompt: string;
  created_at: string;
};

type GenerationLog = {
  id: string;
  model: string;
  credits_used: number;
  created_at: string;
};

type CycleResult = {
  idea: string;
  built: string;
  fixed: string;
  growth: string;
  deployed: string;
  model: string;
};

type ProjectOption = {
  id: string;
  name: string;
  key: string;
  status: string;
};

type AgentStatus = {
  name: string;
  status: "idle" | "running" | "success" | "error";
  updatedAt: string;
};

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserData | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionData>(null);
  const [recentCommands, setRecentCommands] = useState<CommandLog[]>([]);
  const [recentGenerations, setRecentGenerations] = useState<GenerationLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [aiOutput, setAiOutput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isCycling, setIsCycling] = useState(false);
  const [selectedProject, setSelectedProject] = useState("SC-AIC Prime");
  const [projectOptions, setProjectOptions] = useState<ProjectOption[]>([]);
  const [cycleResult, setCycleResult] = useState<CycleResult | null>(null);
  const [agentStatuses, setAgentStatuses] = useState<AgentStatus[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const loadUser = async () => {
      try {
        const response = await fetch("/api/dashboard/overview", { cache: "no-store" });

        if (!response.ok) {
          router.push("/login");
          return;
        }

        const data = (await response.json()) as {
          profile: UserData;
          subscription: SubscriptionData;
          recentCommands: CommandLog[];
          recentGenerations: GenerationLog[];
        };
        setUser(data.profile);
        setSubscription(data.subscription);
        setRecentCommands(data.recentCommands);
        setRecentGenerations(data.recentGenerations);
      } finally {
        setIsLoading(false);
      }
    };

    loadUser().catch(() => {
      router.push("/login");
    });
  }, [router]);

  useEffect(() => {
    const loadProjects = async () => {
      const response = await fetch("/api/projects/list", { cache: "no-store" });

      if (!response.ok) {
        return;
      }

      const data = (await response.json()) as { projects?: ProjectOption[] };
      const projects = data.projects ?? [];
      setProjectOptions(projects);

      if (projects.length && !projects.some((p) => p.name === selectedProject)) {
        setSelectedProject(projects[0].name);
      }
    };

    loadProjects().catch(() => undefined);
  }, [selectedProject]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const loadAgentStatuses = async () => {
      const response = await fetch("/api/agents/status", { cache: "no-store" });

      if (!response.ok) {
        return;
      }

      const data = (await response.json()) as { statuses?: AgentStatus[] };
      setAgentStatuses(data.statuses ?? []);
    };

    loadAgentStatuses().catch(() => undefined);
    timer = setInterval(() => {
      loadAgentStatuses().catch(() => undefined);
    }, 5000);

    return () => {
      if (timer) {
        clearInterval(timer);
      }
    };
  }, []);

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  };

  const handleSubscribe = async () => {
    try {
      const response = await fetch("/api/stripe/checkout", { method: "POST" });

      if (!response.ok) {
        const data = (await response.json()) as { error?: string };
        setMessage(data.error ?? "Unable to create checkout session");
        return;
      }

      const data = (await response.json()) as { url?: string };

      if (!data.url) {
        setMessage("Stripe checkout URL is missing");
        return;
      }

      window.location.href = data.url;
    } catch {
      setMessage("Unable to reach billing service");
    }
  };

  const handleBillingPortal = async () => {
    try {
      const response = await fetch("/api/stripe/portal", { method: "POST" });

      if (!response.ok) {
        const data = (await response.json()) as { error?: string };
        setMessage(data.error ?? "Unable to open billing portal");
        return;
      }

      const data = (await response.json()) as { url?: string };

      if (!data.url) {
        setMessage("Billing portal URL is missing");
        return;
      }

      window.location.href = data.url;
    } catch {
      setMessage("Unable to reach billing portal service");
    }
  };

  const handleGenerate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!prompt.trim()) {
      return;
    }

    setIsGenerating(true);
    setMessage(null);

    try {
      const response = await fetch("/api/ai/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt }),
      });

      if (!response.ok) {
        const data = (await response.json()) as { error?: string };
        setMessage(data.error ?? "AI request failed");
        setIsGenerating(false);
        return;
      }

      const data = (await response.json()) as { output?: string };
      setAiOutput(data.output ?? "No output received");
    } catch {
      setMessage("Unable to reach AI service");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCycle = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!prompt.trim()) {
      setMessage("AI command is required");
      return;
    }

    setIsCycling(true);
    setMessage(null);

    try {
      const response = await fetch("/api/ai/cycle", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          command: prompt,
          project: selectedProject,
          phase: "Phase 1 - Core MVP",
        }),
      });

      if (!response.ok) {
        const data = (await response.json()) as { error?: string };
        setMessage(data.error ?? "AI cycle request failed");
        return;
      }

      const data = (await response.json()) as {
        result?: CycleResult;
        creditsUsed?: number;
      };

      if (!data.result) {
        setMessage("No cycle result returned");
        return;
      }

      setCycleResult(data.result);
      setAiOutput(data.result.deployed);
      setMessage(
        `AI cycle completed on ${selectedProject} (${data.result.model}) • credits: ${data.creditsUsed ?? 0}`,
      );
    } catch {
      setMessage("Unable to reach AI cycle service");
    } finally {
      setIsCycling(false);
    }
  };

  if (isLoading) {
    return (
      <main className="mx-auto w-full max-w-5xl p-6">
        <p className="text-sm text-zinc-600">Loading dashboard...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 p-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Command Dashboard</h1>
        <button
          type="button"
          onClick={handleLogout}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100"
        >
          Logout
        </button>
      </div>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">User System</h2>
        <p className="mt-2 text-sm text-zinc-700">Email: {user?.email ?? "Unknown"}</p>
        <p className="text-sm text-zinc-700">Name: {user?.fullName ?? "Not set"}</p>
        <p className="text-sm text-zinc-700">Role: {user?.role ?? "user"}</p>
        <p className="text-sm text-zinc-700">Plan: {user?.plan ?? "free"}</p>
        <p className="text-sm text-zinc-700">AI Credits: {user?.aiCredits ?? 0}</p>
        {user?.isDev ? (
          <p className="mt-2 text-sm font-medium text-emerald-700">
            Developer access is active for this account.
          </p>
        ) : null}
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">Billing</h2>
        <p className="mt-2 text-sm text-zinc-600">
          {user?.isDev
            ? "Developer accounts already have full access."
            : "Start subscription checkout to unlock premium tools."}
        </p>
        <p className="mt-2 text-sm text-zinc-700">
          Subscription status: {subscription?.status ?? "inactive"}
        </p>
        <p className="text-sm text-zinc-700">
          Current period end: {subscription?.current_period_end ?? "-"}
        </p>
        <button
          type="button"
          onClick={handleSubscribe}
          disabled={user?.isDev}
          className="mt-4 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
        >
          Upgrade with Stripe
        </button>
        <button
          type="button"
          onClick={handleBillingPortal}
          disabled={user?.isDev}
          className="mt-4 ml-3 rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-800 hover:bg-zinc-100"
        >
          Open billing portal
        </button>
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">AI Command System</h2>
        <form onSubmit={handleCycle} className="mt-4 space-y-3">
          <label className="block text-sm font-medium text-zinc-700">Project</label>
          <select
            value={selectedProject}
            onChange={(event) => setSelectedProject(event.target.value)}
            className="w-full rounded-md border border-zinc-300 p-2 text-sm outline-none focus:border-zinc-500"
          >
            {projectOptions.length ? (
              projectOptions.map((project) => (
                <option key={project.id} value={project.name}>
                  {project.name}
                </option>
              ))
            ) : (
              <option>SC-AIC Prime</option>
            )}
          </select>
          <button
            type="submit"
            disabled={isCycling}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60"
          >
            {isCycling ? "Running cycle..." : "Run AI Command Cycle"}
          </button>
        </form>

        {cycleResult ? (
          <div className="mt-4 space-y-3 text-sm">
            <div className="rounded-md bg-zinc-50 p-3">
              <p className="font-medium text-zinc-900">1) Product Idea</p>
              <p className="mt-1 whitespace-pre-wrap text-zinc-700">{cycleResult.idea}</p>
            </div>
            <div className="rounded-md bg-zinc-50 p-3">
              <p className="font-medium text-zinc-900">2) Builder Output</p>
              <p className="mt-1 whitespace-pre-wrap text-zinc-700">{cycleResult.built}</p>
            </div>
            <div className="rounded-md bg-zinc-50 p-3">
              <p className="font-medium text-zinc-900">3) Debugger Output</p>
              <p className="mt-1 whitespace-pre-wrap text-zinc-700">{cycleResult.fixed}</p>
            </div>
            <div className="rounded-md bg-zinc-50 p-3">
              <p className="font-medium text-zinc-900">4) Growth Output</p>
              <p className="mt-1 whitespace-pre-wrap text-zinc-700">{cycleResult.growth}</p>
            </div>
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">Agent Status (Real-time)</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {agentStatuses.length ? (
            agentStatuses.map((agent) => (
              <div key={agent.name} className="rounded-md bg-zinc-50 p-3 text-sm">
                <p className="font-medium text-zinc-900">{agent.name}</p>
                <p className="mt-1 text-zinc-700">Status: {agent.status}</p>
                <p className="mt-1 text-xs text-zinc-500">Updated: {agent.updatedAt}</p>
              </div>
            ))
          ) : (
            <p className="text-sm text-zinc-500">No agent status available yet.</p>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">AI Generate</h2>
        <form onSubmit={handleGenerate} className="mt-4 space-y-3">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Describe your automation request..."
            className="min-h-28 w-full rounded-md border border-zinc-300 p-3 text-sm outline-none focus:border-zinc-500"
          />
          <button
            type="submit"
            disabled={isGenerating}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60"
          >
            {isGenerating ? "Generating..." : "Generate"}
          </button>
        </form>
        {aiOutput ? (
          <pre className="mt-4 whitespace-pre-wrap rounded-md bg-zinc-50 p-3 text-sm text-zinc-800">
            {aiOutput}
          </pre>
        ) : null}
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">Recent Commands</h2>
        <div className="mt-3 space-y-3">
          {recentCommands.length ? (
            recentCommands.map((command) => (
              <div key={command.id} className="rounded-md bg-zinc-50 p-3 text-sm">
                <p className="font-medium text-zinc-900">{command.command_type}</p>
                <p className="text-zinc-600">{command.prompt}</p>
                <p className="mt-1 text-xs text-zinc-500">
                  {command.status} • {command.created_at}
                </p>
              </div>
            ))
          ) : (
            <p className="text-sm text-zinc-500">No commands recorded yet.</p>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 p-4">
        <h2 className="text-lg font-semibold">Recent AI Usage</h2>
        <div className="mt-3 space-y-3">
          {recentGenerations.length ? (
            recentGenerations.map((generation) => (
              <div key={generation.id} className="rounded-md bg-zinc-50 p-3 text-sm">
                <p className="font-medium text-zinc-900">{generation.model}</p>
                <p className="text-zinc-600">Credits used: {generation.credits_used}</p>
                <p className="mt-1 text-xs text-zinc-500">{generation.created_at}</p>
              </div>
            ))
          ) : (
            <p className="text-sm text-zinc-500">No AI usage recorded yet.</p>
          )}
        </div>
      </section>

      {message ? <p className="text-sm text-red-600">{message}</p> : null}
    </main>
  );
}
