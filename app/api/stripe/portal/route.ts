import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getEnv, getOptionalEnv } from "@/lib/env";
import { getAuthenticatedUser } from "@/lib/server/session";
import { createAdminSupabaseClient } from "@/lib/server/supabase-admin";

export const runtime = "nodejs";

export async function POST() {
  try {
    const user = await getAuthenticatedUser();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const supabase = createAdminSupabaseClient();
    const appUrl = getOptionalEnv("NEXT_PUBLIC_APP_URL") ?? "http://localhost:3000";
    const stripe = new Stripe(getEnv("STRIPE_SECRET_KEY"));

    if (!supabase) {
      return NextResponse.json(
        { error: "Missing SUPABASE_SERVICE_ROLE_KEY" },
        { status: 500 },
      );
    }

    const { data } = await supabase
      .from("subscriptions")
      .select("stripe_customer_id")
      .eq("user_id", user.id)
      .maybeSingle<{ stripe_customer_id: string | null }>();

    let customerId = data?.stripe_customer_id ?? null;

    if (!customerId && user.email) {
      const customers = await stripe.customers.list({
        email: user.email,
        limit: 1,
      });
      customerId = customers.data[0]?.id ?? null;
    }

    if (!customerId) {
      const customer = await stripe.customers.create({
        email: user.email ?? undefined,
        metadata: {
          user_id: user.id,
        },
      });
      customerId = customer.id;
    }

    await supabase.from("subscriptions").upsert(
      {
        user_id: user.id,
        stripe_customer_id: customerId,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" },
    );

    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: `${appUrl}/dashboard`,
    });

    return NextResponse.json({ url: session.url });
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Unable to create billing portal",
      },
      { status: 500 },
    );
  }
}
