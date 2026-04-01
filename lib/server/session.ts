import { cookies } from "next/headers";
import { createSupabaseClient } from "@/lib/supabase";

export const ACCESS_TOKEN_COOKIE = "scaic_access_token";
export const REFRESH_TOKEN_COOKIE = "scaic_refresh_token";

export type AuthenticatedUser = {
  id: string;
  email: string | null;
};

export async function getAuthenticatedUser(): Promise<AuthenticatedUser | null> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;

  if (!accessToken) {
    return null;
  }

  const supabase = createSupabaseClient();
  const { data, error } = await supabase.auth.getUser(accessToken);

  if (error || !data.user) {
    return null;
  }

  return {
    id: data.user.id,
    email: data.user.email ?? null,
  };
}
