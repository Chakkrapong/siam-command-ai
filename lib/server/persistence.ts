import type Stripe from "stripe";
import { createAdminSupabaseClient } from "@/lib/server/supabase-admin";

export type ProfileRecord = {
  id: string;
  email?: string | null;
  full_name?: string | null;
  plan?: string | null;
  ai_credits?: number | null;
  last_login_at?: string;
};

export async function upsertProfile(profile: ProfileRecord) {
  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return;
  }

  await supabase.from("profiles").upsert(profile, { onConflict: "id" });
}

export async function logCommand(input: {
  userId: string;
  commandType: string;
  prompt: string;
  output?: string | null;
  status: "success" | "error";
  metadata?: Record<string, unknown>;
}) {
  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return;
  }

  await supabase.from("command_logs").insert({
    user_id: input.userId,
    command_type: input.commandType,
    prompt: input.prompt,
    output: input.output ?? null,
    status: input.status,
    metadata: input.metadata ?? {},
  });
}

export async function logAiUsage(input: {
  userId: string;
  model: string;
  prompt: string;
  output: string;
  creditsUsed: number;
  skipCreditDecrement?: boolean;
}) {
  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return;
  }

  await supabase.from("ai_generations").insert({
    user_id: input.userId,
    model: input.model,
    prompt: input.prompt,
    output: input.output,
    credits_used: input.creditsUsed,
  });

  if (input.skipCreditDecrement) {
    return;
  }

  await supabase.rpc("decrement_ai_credits", {
    target_user_id: input.userId,
    used_credits: input.creditsUsed,
  });
}

export async function upsertSubscriptionFromCheckout(session: Stripe.Checkout.Session) {
  const supabase = createAdminSupabaseClient();
  const userId = session.metadata?.user_id ?? session.client_reference_id;

  if (!supabase || !userId) {
    return;
  }

  await supabase.from("subscriptions").upsert(
    {
      user_id: userId,
      stripe_customer_id: typeof session.customer === "string" ? session.customer : null,
      stripe_subscription_id:
        typeof session.subscription === "string" ? session.subscription : null,
      stripe_price_id: null,
      status: session.payment_status === "paid" ? "active" : "incomplete",
      current_period_end: null,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "user_id" },
  );

  await supabase
    .from("profiles")
    .update({ plan: "pro" })
    .eq("id", userId);
}

export async function updateSubscriptionStatus(input: {
  userId?: string | null;
  subscriptionId: string;
  customerId?: string | null;
  priceId?: string | null;
  status: string;
  currentPeriodEnd?: Date | null;
}) {
  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return;
  }

  const { data: existingBySubscription } = await supabase
    .from("subscriptions")
    .select("user_id")
    .eq("stripe_subscription_id", input.subscriptionId)
    .maybeSingle<{ user_id: string }>();

  let resolvedUserId = input.userId ?? existingBySubscription?.user_id ?? null;

  if (!resolvedUserId && input.customerId) {
    const { data: existingByCustomer } = await supabase
      .from("subscriptions")
      .select("user_id")
      .eq("stripe_customer_id", input.customerId)
      .not("user_id", "is", null)
      .maybeSingle<{ user_id: string }>();

    resolvedUserId = existingByCustomer?.user_id ?? null;
  }

  await supabase.from("subscriptions").upsert(
    {
      user_id: resolvedUserId,
      stripe_customer_id: input.customerId ?? null,
      stripe_subscription_id: input.subscriptionId,
      stripe_price_id: input.priceId ?? null,
      status: input.status,
      current_period_end: input.currentPeriodEnd?.toISOString() ?? null,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "stripe_subscription_id" },
  );

  if (resolvedUserId) {
    const isProPlan = input.status === "active" || input.status === "trialing";

    await supabase
      .from("profiles")
      .update({ plan: isProPlan ? "pro" : "free" })
      .eq("id", resolvedUserId);
  }
}

export async function markStripeEventProcessed(input: {
  eventId: string;
  eventType: string;
}): Promise<boolean> {
  const supabase = createAdminSupabaseClient();

  if (!supabase) {
    return true;
  }

  const { error } = await supabase.from("stripe_events").insert({
    event_id: input.eventId,
    event_type: input.eventType,
    processed_at: new Date().toISOString(),
  });

  if (!error) {
    return true;
  }

  if (error.code === "23505") {
    return false;
  }

  throw new Error(error.message);
}
