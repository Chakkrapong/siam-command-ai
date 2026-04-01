import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getEnv, getOptionalEnv } from "@/lib/env";
import {
  markStripeEventProcessed,
  updateSubscriptionStatus,
} from "@/lib/server/persistence";

export const runtime = "nodejs";

function getSubscriptionPeriodEnd(subscription: Stripe.Subscription): Date | null {
  const periodEnd = subscription.items.data[0]?.current_period_end;
  return periodEnd ? new Date(periodEnd * 1000) : null;
}

export async function POST(request: Request) {
  const stripe = new Stripe(getEnv("STRIPE_SECRET_KEY"));
  const webhookSecret = getOptionalEnv("STRIPE_WEBHOOK_SECRET");

  if (!webhookSecret) {
    return NextResponse.json(
      { error: "Missing STRIPE_WEBHOOK_SECRET" },
      { status: 500 },
    );
  }

  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json(
      { error: "Missing stripe-signature header" },
      { status: 400 },
    );
  }

  const payload = await request.text();

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(payload, signature, webhookSecret);
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Unable to verify Stripe webhook",
      },
      { status: 400 },
    );
  }

  const shouldProcess = await markStripeEventProcessed({
    eventId: event.id,
    eventType: event.type,
  });

  if (!shouldProcess) {
    return NextResponse.json({ received: true, duplicate: true });
  }

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;

      if (typeof session.subscription === "string") {
        const subscription = await stripe.subscriptions.retrieve(session.subscription);
        const subscriptionUserId =
          subscription.metadata?.user_id ??
          session.metadata?.user_id ??
          session.client_reference_id ??
          null;

        await updateSubscriptionStatus({
          userId: subscriptionUserId,
          subscriptionId: subscription.id,
          customerId:
            typeof subscription.customer === "string" ? subscription.customer : null,
          priceId: subscription.items.data[0]?.price.id ?? null,
          status: subscription.status,
          currentPeriodEnd: getSubscriptionPeriodEnd(subscription),
        });
      }
      break;
    }
    case "customer.subscription.created":
    case "customer.subscription.updated": {
      const subscription = event.data.object as Stripe.Subscription;

      await updateSubscriptionStatus({
        userId: subscription.metadata?.user_id ?? null,
        subscriptionId: subscription.id,
        customerId:
          typeof subscription.customer === "string" ? subscription.customer : null,
        priceId: subscription.items.data[0]?.price.id ?? null,
        status: subscription.status,
        currentPeriodEnd: getSubscriptionPeriodEnd(subscription),
      });
      break;
    }
    case "checkout.session.async_payment_failed": {
      const session = event.data.object as Stripe.Checkout.Session;

      if (typeof session.subscription === "string") {
        const subscription = await stripe.subscriptions.retrieve(session.subscription);

        await updateSubscriptionStatus({
          userId:
            subscription.metadata?.user_id ??
            session.metadata?.user_id ??
            session.client_reference_id ??
            null,
          subscriptionId: subscription.id,
          customerId:
            typeof subscription.customer === "string" ? subscription.customer : null,
          priceId: subscription.items.data[0]?.price.id ?? null,
          status: subscription.status,
          currentPeriodEnd: getSubscriptionPeriodEnd(subscription),
        });
      }

      break;
    }
    case "invoice.paid":
    case "invoice.payment_failed": {
      const invoice = event.data.object as Stripe.Invoice;

      const invoiceSubscription = invoice.parent?.subscription_details?.subscription;
      const subscriptionId =
        typeof invoiceSubscription === "string"
          ? invoiceSubscription
          : invoiceSubscription?.id;

      if (subscriptionId) {
        const subscription = await stripe.subscriptions.retrieve(subscriptionId);

        await updateSubscriptionStatus({
          userId: subscription.metadata?.user_id ?? null,
          subscriptionId: subscription.id,
          customerId:
            typeof subscription.customer === "string" ? subscription.customer : null,
          priceId: subscription.items.data[0]?.price.id ?? null,
          status: subscription.status,
          currentPeriodEnd: getSubscriptionPeriodEnd(subscription),
        });
      }

      break;
    }
    case "customer.subscription.deleted": {
      const subscription = event.data.object as Stripe.Subscription;

      await updateSubscriptionStatus({
        userId: subscription.metadata?.user_id ?? null,
        subscriptionId: subscription.id,
        customerId:
          typeof subscription.customer === "string" ? subscription.customer : null,
        priceId: subscription.items.data[0]?.price.id ?? null,
        status: subscription.status,
        currentPeriodEnd: null,
      });
      break;
    }
    default:
      break;
  }

  return NextResponse.json({ received: true });
}
