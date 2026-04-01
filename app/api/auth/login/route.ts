import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { createSupabaseClient } from "@/lib/supabase";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/server/session";
import { upsertProfile } from "@/lib/server/persistence";

export async function POST(request: Request) {
  try {
    const { email, password } = (await request.json()) as {
      email?: string;
      password?: string;
    };

    if (!email || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 },
      );
    }

    const supabase = createSupabaseClient();
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error || !data.session || !data.user) {
      return NextResponse.json(
        { error: error?.message ?? "Invalid credentials" },
        { status: 401 },
      );
    }

    const cookieStore = await cookies();
    const maxAge = Math.max(60, data.session.expires_in ?? 60 * 60 * 8);
    const secure = process.env.NODE_ENV === "production";

    await upsertProfile({
      id: data.user.id,
      email: data.user.email ?? email,
      full_name:
        typeof data.user.user_metadata.full_name === "string"
          ? data.user.user_metadata.full_name
          : null,
      last_login_at: new Date().toISOString(),
    });

    cookieStore.set(ACCESS_TOKEN_COOKIE, data.session.access_token, {
      httpOnly: true,
      secure,
      sameSite: "lax",
      path: "/",
      maxAge,
    });

    cookieStore.set(REFRESH_TOKEN_COOKIE, data.session.refresh_token, {
      httpOnly: true,
      secure,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });

    return NextResponse.json({
      user: {
        id: data.user.id,
        email: data.user.email,
      },
    });
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }
}
