import { NextResponse } from "next/server";
import { getAuthenticatedUser } from "@/lib/server/session";
import { createAdminSupabaseClient } from "@/lib/server/supabase-admin";

type ProjectRecord = {
  id: string;
  name: string;
  key: string;
  status: string;
};

const fallbackProjects: ProjectRecord[] = [
  { id: "p-core", name: "SC-AIC Prime", key: "sc-aic-prime", status: "active" },
  { id: "p-forgemind", name: "ForgeMind X", key: "forgemind-x", status: "active" },
  { id: "p-security", name: "AI Security System", key: "ai-security", status: "active" },
  { id: "p-music", name: "AI Music Empire", key: "ai-music", status: "active" },
];

export async function GET() {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return NextResponse.json({ projects: fallbackProjects });
  }

  const { data, error } = await supabase
    .from("projects")
    .select("id, name, key, status")
    .order("name", { ascending: true });

  if (error) {
    return NextResponse.json({ projects: fallbackProjects });
  }

  return NextResponse.json({ projects: data ?? fallbackProjects });
}
