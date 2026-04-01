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

    const stripe = new Stripe(getEnv("STRIPE_SECRET_KEY"));
    const priceId = getEnv("STRIPE_PRICE_ID");
    const appUrl = getOptionalEnv("NEXT_PUBLIC_APP_URL") ?? "http://localhost:3000";
    const supabase = createAdminSupabaseClient();

    let customerId: string | null = null;
    let subscriptionStatus: string | null = null;

    if (supabase) {
      const { data } = await supabase
        .from("subscriptions")
        .select("stripe_customer_id, status")
        .eq("user_id", user.id)
        .maybeSingle<{ stripe_customer_id: string | null; status: string | null }>();

      customerId = data?.stripe_customer_id ?? null;
      subscriptionStatus = data?.status ?? null;
    }

    if (subscriptionStatus === "active" || subscriptionStatus === "trialing") {
      return NextResponse.json(
        {
          error: "Subscription is already active. Use billing portal to manage your plan.",
        },
        { status: 409 },
      );
    }

    if (!customerId && user.email) {
      const customers = await stripe.customers.list({
        email: user.email,
        limit: 1,
      });

      customerId = customers.data[0]?.id ?? null;
    }

    if (supabase && customerId) {
      await supabase.from("subscriptions").upsert(
        {
          user_id: user.id,
          stripe_customer_id: customerId,
          updated_at: new Date().toISOString(),
        },
        { onConflict: "user_id" },
      );
    }

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${appUrl}/dashboard?billing=success`,
      cancel_url: `${appUrl}/dashboard?billing=cancelled`,
      customer: customerId ?? undefined,
      customer_email: customerId ? undefined : user.email ?? undefined,
      allow_promotion_codes: true,
      locale: "th",
      client_reference_id: user.id,
      metadata: {
        user_id: user.id,
      },
      subscription_data: {
        metadata: {
          user_id: user.id,
        },
      },
    });

    return NextResponse.json({ url: session.url });
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Unable to create Stripe checkout",
      },
      { status: 500 },
    );
  }
}
