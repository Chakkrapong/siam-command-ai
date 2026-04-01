import { NextResponse } from "next/server";
import { getEffectiveAccess } from "@/lib/server/access";
import { getAuthenticatedUser } from "@/lib/server/session";
import { createAdminSupabaseClient } from "@/lib/server/supabase-admin";

export async function GET() {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    const access = getEffectiveAccess({ email: user.email });

    return NextResponse.json(
      {
        profile: {
          id: user.id,
          email: user.email,
          fullName: null,
          role: access.role,
          isDev: access.isDev,
          plan: access.plan,
          aiCredits: access.aiCredits,
        },
        subscription: null,
        recentCommands: [],
        recentGenerations: [],
      },
      { status: 200 },
    );
  }

  const [{ data: profile }, { data: subscription }, { data: recentCommands }, { data: recentGenerations }] =
    await Promise.all([
      supabase
        .from("profiles")
        .select("id, email, full_name, plan, ai_credits")
        .eq("id", user.id)
        .maybeSingle<{
          id: string;
          email: string | null;
          full_name: string | null;
          plan: string | null;
          ai_credits: number | null;
        }>(),
      supabase
        .from("subscriptions")
        .select("status, stripe_price_id, current_period_end")
        .eq("user_id", user.id)
        .maybeSingle<{
          status: string;
          stripe_price_id: string | null;
          current_period_end: string | null;
        }>(),
      supabase
        .from("command_logs")
        .select("id, command_type, status, prompt, created_at")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(5),
      supabase
        .from("ai_generations")
        .select("id, model, credits_used, created_at")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(5),
    ]);

  const access = getEffectiveAccess({
    email: profile?.email ?? user.email,
    plan: profile?.plan,
    aiCredits: profile?.ai_credits,
  });

  return NextResponse.json({
    profile: {
      id: user.id,
      email: profile?.email ?? user.email,
      fullName: profile?.full_name ?? null,
      role: access.role,
      isDev: access.isDev,
      plan: access.plan,
      aiCredits: access.aiCredits,
    },
    subscription,
    recentCommands: recentCommands ?? [],
    recentGenerations: recentGenerations ?? [],
  });
}
