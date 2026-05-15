# Good Post Example — Story Hook (Debugging/Distributed Systems)

## Final LinkedIn Post

Yesterday I spent 4 hours debugging a workflow that silently stopped processing events.

Here's what I found.

Our Temporal workflow was handling order fulfillment. It worked perfectly for months. Then one day, orders started piling up with no processing.

No errors in logs. No failed activities. Health checks passing.

The root cause was a non-deterministic workflow definition. We'd added a new `datetime.now()` call inside the workflow logic:

    # BROKEN — non-deterministic in workflow code
    if datetime.now() > deadline:
        await cancel_order(order_id)

Temporal replays workflow history to recover state. But `datetime.now()` returns a different value on replay than the original execution. This caused the workflow to diverge and silently deadlock.

The fix:

    # CORRECT — use Temporal's deterministic time
    if workflow.now() > deadline:
        await cancel_order(order_id)

One character difference. 4 hours of debugging.

The lesson: in any durable execution system, side effects inside orchestration logic are bugs waiting to happen. Pure functions in workflows, side effects in activities.

We added a lint rule to catch `datetime.now()`, `random()`, and `uuid4()` inside workflow files. Zero recurrence since.

What's your most painful "it was one line" debugging story?
