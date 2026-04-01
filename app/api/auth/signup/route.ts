import { NextResponse } from "next/server";
import { isDeveloperEmail } from "@/lib/server/access";
import { createSupabaseClient } from "@/lib/supabase";
import { upsertProfile } from "@/lib/server/persistence";

export async function POST(request: Request) {
  try {
    const { email, password, fullName } = (await request.json()) as {
      email?: string;
      password?: string;
      fullName?: string;
    };

    if (!email || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 },
      );
    }

    const supabase = createSupabaseClient();
    const isDev = isDeveloperEmail(email);
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: fullName ?? null,
        },
      },
    });

    if (error || !data.user) {
      return NextResponse.json(
        { error: error?.message ?? "Unable to create account" },
        { status: 400 },
      );
    }

    await upsertProfile({
      id: data.user.id,
      email: data.user.email ?? email,
      full_name: fullName ?? null,
      plan: isDev ? "dev" : "free",
      ai_credits: isDev ? 999999 : 100,
    });

    return NextResponse.json({
      user: {
        id: data.user.id,
        email: data.user.email,
      },
      needsEmailConfirmation: !data.session,
    });
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }
}
