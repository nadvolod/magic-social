# Good Post Example — Contrarian Hook (Temporal/Distributed Systems)

## Final LinkedIn Post

Most engineers retry failed API calls with exponential backoff.

They're solving the wrong problem.

I spent 3 days debugging a payment processing pipeline that was "working" — retries were firing, requests were succeeding on retry.

But we were charging customers twice.

The root cause: our retry logic had no idempotency key. Every retry was a new request to Stripe.

The fix was 4 lines:

    activity_options = ActivityOptions(
        retry_policy=RetryPolicy(max_attempts=3),
        idempotency_key=f"payment-{order_id}-{attempt}",
    )

After adding this to our Temporal workflow activities, duplicate charges dropped from ~2% to 0%.

The lesson isn't "add retries." It's: retries without idempotency are a liability, not a safety net.

Every distributed system I've worked on had this bug hiding somewhere. The scary part is it looks like everything works — until you check the billing data.

What's the most expensive retry bug you've shipped?
