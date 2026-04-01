import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ACCESS_TOKEN_COOKIE } from "@/lib/server/session";

export default async function Home() {
  const cookieStore = await cookies();
  const hasSession = Boolean(cookieStore.get(ACCESS_TOKEN_COOKIE)?.value);

  redirect(hasSession ? "/dashboard" : "/login");
}
