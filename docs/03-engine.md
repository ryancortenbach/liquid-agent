# 03: Deadline and routing engine

Liquid maximizes the expected net value of a sale that closes before the seller's deadline. It
does not process the payment. Marketplace order signals and seller confirmations determine whether
a deal actually closed.

## Objective

```text
maximize    expected net proceeds before deadline
subject to  price >= seller floor
            no acceptance after deadline
            at most one active sale claim
            at most one confirmed sale
            assisted publishing requires seller approval
choices     HOLD, REPRICE, BROADCAST, COUNTER, ACCEPT, ROUTE, ESCALATE, EXPIRE
```

## Demand model

Let market value be `M`, spread be `sigma`, price be `p`, and remaining hours be `tau`.

```text
q(p) = 1 - NormalCDF((p - M) / sigma)
lambda_c(p) = arrival_rate_c * q(p)
P(tau, p) = 1 - exp(-tau * sum(lambda_c(p)))
```

The channel arrival rate uses a Gamma-Poisson update. Views and saves count as fractional
inquiries. Quiet time lowers the posterior arrival rate.

Net proceeds are marketplace price minus the documented channel fee and expected shipping cost.
The engine searches the cent-safe dollar grid from the seller floor to `1.3 * M`.

```text
V(p, tau) = P(tau, p) * weighted_channel_net(p) + (1 - P(tau, p)) * salvage
p_star(tau) = argmax V(p, tau)
```

## Liquidity frontier

For 24, 72, and 168 hours, the frontier reports the largest price with at least an 85 percent
modeled close probability. An instant or trade-in quote is shown only when a real or clearly
disclosed modeled route exists.

## Offers

An offer arrives from a marketplace channel. `r_b` is that buyer and channel's estimated close
reliability. `s_b` is the expected time to close.

```text
EV_accept = r_b * net(offer) + (1 - r_b) * V(p_star(tau - s_b), tau - s_b)
EV_continue = V(p_star(tau), tau)
```

- Accept when the offer is at or above the floor and its expected value beats continuing.
- Otherwise counter at the lowest rounded price whose close-adjusted net beats continuing.
- Never reveal the floor, deadline pressure, or another buyer's offer in marketplace messages.
- Seller approval is required when policy or channel permissions require it.

## Cross-channel sale claim

Acceptance is a two-stage operation:

1. Create an ACTIVE `SaleClaim` in the same transaction as the ledger event.
2. Pause every competing listing through the outbox.
3. Accept or reserve the winning marketplace offer.
4. Confirm SOLD only from a trusted marketplace order event or explicit seller confirmation.
5. End every remaining listing.

If the buyer withdraws, does not show, or the marketplace cancels the transaction, the claim becomes
RELEASED and eligible listings resume immediately.

## Repricing

- Reprice only when the optimal price is lower by at least 2 percent or $3.
- Wait at least `max(1 hour, original horizon / 12)` between reductions.
- Never raise a live listing unless the seller changes the deadline or floor and approves a replan.
- Apply the price to every supported live channel. Create approval tasks for assisted channels.

## Endgame

The escalation window is `max(2 hours, 5 percent of the original horizon)`.

- If no executable offer meets the floor, ask the seller to accept the best offer, wait, or extend.
- At the deadline, take a preauthorized instant route if one exists. Otherwise expire and summarize.

## Policy outline

```python
def decide(state, now):
    tau = hours_until(state.deadline_at, now)

    if state.status == SALE_PENDING:
        return Hold()
    if state.status not in (LIVE, ESCALATED):
        return Hold()
    if tau <= 0:
        return RouteInstant() if state.instant_preauthorized else Expire()

    target = optimal_price(state, tau)
    best = best_open_marketplace_offer(state)

    if best and best.amount >= state.floor and ev_accept(best) >= target.expected_value:
        return Accept(best)
    if unanswered_offer(state):
        return Counter(within_engine_bounds=True)
    if in_endgame(tau) and no_offer_meets_floor(state):
        return Escalate()
    if should_reprice(state, target, now):
        return Reprice(target)
    return Hold()
```

The same function runs in real time, accelerated demos, and simulation.
