import { NextResponse } from "next/server";
import { getEffectiveAccess } from "@/lib/server/access";
import { getAuthenticatedUser } from "@/lib/server/session";
import { createSupabaseClient } from "@/lib/supabase";

type ProfileRow = {
  id: string;
  full_name: string | null;
  plan: string | null;
  ai_credits: number | null;
};

export async function GET() {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabase = createSupabaseClient();
  const { data } = await supabase
    .from("profiles")
    .select("id, full_name, plan, ai_credits")
    .eq("id", user.id)
    .maybeSingle<ProfileRow>();

  const access = getEffectiveAccess({
    email: user.email,
    plan: data?.plan,
    aiCredits: data?.ai_credits,
  });

  return NextResponse.json({
    user: {
      id: user.id,
      email: user.email,
      fullName: data?.full_name ?? null,
      role: access.role,
      isDev: access.isDev,
      plan: access.plan,
      aiCredits: access.aiCredits,
    },
  });
}
