import { NextResponse } from "next/server";
import { createSupabaseClient } from "@/lib/supabase";
import { getOptionalEnv } from "@/lib/env";

export async function POST(request: Request) {
  try {
    const { email } = (await request.json()) as { email?: string };

    if (!email) {
      return NextResponse.json({ error: "Email is required" }, { status: 400 });
    }

    const appUrl = getOptionalEnv("NEXT_PUBLIC_APP_URL") ?? "http://localhost:3000";
    const supabase = createSupabaseClient();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${appUrl}/login`,
    });

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }

    return NextResponse.json({ success: true });
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }
}
