import { createClient } from "@supabase/supabase-js";
import { getEnv } from "@/lib/env";

export function createSupabaseClient() {
  return createClient(
    getEnv("NEXT_PUBLIC_SUPABASE_URL"),
    getEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
  );
}
