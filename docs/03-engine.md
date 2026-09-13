# 03 · The liquidation engine

This is the part that earns "technical execution". It is a small, explainable trading algorithm for one physical item under a deadline. Everything is deterministic given the state and the clock, so every decision in the demo can be reproduced from its ledger row.

## The problem
```
maximize    E[ net proceeds that clear before the deadline ]
subject to  price ≥ floor · sale_time ≤ deadline · at most one sale
            payment verified before "sold" · pickup fits the calendar
choices     HOLD · REPRICE · BROADCAST · COUNTER · ACCEPT · ROUTE_INSTANT · ESCALATE · EXPIRE
```

## Inputs
| Symbol | Meaning | Source |
|---|---|---|
| M | market value estimate, dollars | median of cleaned used comps × realization haircut h = 0.92 |
| σ | spread of buyers' willingness to pay | max(0.10·M, IQR(comps)/1.35) |
| F | seller floor | seller's words, else derived = max(instant quote, 0.75·M) |
| τ | hours until deadline | clock |
| a_c | arrival rate of interested buyers per hour on channel c | Gamma-Poisson posterior, updated from inquiries and views |
| fee_c(p), ship_c | channel costs | fees.py |
| S | salvage: net of the instant quote if the seller allows instant, else 0 | instant channel |
| r_b, s_b | buyer b's payment reliability and settlement time | buyer table, defaults by channel |

Channels c ∈ {ebay, local, instant}.

## Demand model
A buyer with willingness to pay W ~ Normal(M, σ) buys at price p if W ≥ p:
```
q(p) = 1 − Φ((p − M) / σ)
```
Buyers arrive on channel c as a Poisson process with rate a_c, so sales at price p arrive at rate
```
λ_c(p) = a_c · q(p)
```
and the probability of at least one sale within τ hours is
```
P(τ, p) = 1 − exp( −τ · Σ_c λ_c(p) )
```
That is the whole model. It is one line, monotone in p and τ, and it produces the pitch's behaviour: as τ falls, the price that maximizes expected value falls with it.

## Objective and the price rule
Net proceeds on channel c: `n_c(p) = p − fee_c(p) − ship_c`.
Arrival-weighted net across channels: `n̄(p) = Σ_c λ_c(p)·n_c(p) / Σ_c λ_c(p)`.
Expected value of running the strategy at price p with τ hours left:
```
V(p, τ) = P(τ, p) · n̄(p) + (1 − P(τ, p)) · S
```
Optimal price:
```
p*(τ) = argmax over the grid { F, F+1, …, 1.3·M } of V(p, τ)
```
Grid search, not calculus, so anyone can read it and the ledger can show the top three candidates.

## Liquidity frontier
For each horizon h in {24h, 72h, 168h}: `p_h` = the largest grid price with `P(h, p) ≥ 0.85`.
Sell now = the instant quote S, or "no instant option" if the seller disallows it.
Texted as: `$S guaranteed now / ~$p_24 likely today / ~$p_72 likely within 3 days`.
The opening list price is `p*(τ_deadline)`, never above 1.3·M and never below F.

## Learning from the market
Arrival rate prior per channel and category, for example headphones: `a_local ~ Gamma(2, 24h)` (mean 2 per day), `a_ebay ~ Gamma(4, 24h)` (mean 4 per day). Priors live in one file, `engine/priors.yaml`.
Observed k inquiries in t elapsed hours on channel c:
```
a_c = (α0 + k) / (β0 + t)
```
Views count as fractional inquiries: `k += ρ · views`, ρ = 0.05.
No inquiries in 24 hours is information: the posterior mean falls, P(τ, p) falls, p* falls. That is the "lots of looks, no takers" beat.
P1: treat offers as censored samples of W and move M with them.

## Offers
Buyer b offers amount o on channel c.
```
EV_acc  = r_b · n_c(o)  +  (1 − r_b) · V( p*(τ − s_b), τ − s_b )     # if payment fails we are back in the market with less time
EV_cont = V( p*(τ), τ )
```
- **ACCEPT** if `o ≥ F` and `EV_acc ≥ EV_cont`.
- Otherwise **COUNTER** at the smallest grid price p with `r_b · n_c(p) ≥ EV_cont`, rounded up to $5, capped at the current list price, never below F. At most 2 counters per buyer per 24 simulated hours; after that the reply is "that's where it sits today" at the current price.
- An offer below F is never accepted. It is countered at ≥ F, never insulted.
- Anyone who inquired or offered stays in the interested pool for broadcasts.

## Repricing
At each tick with `p* = p*(τ)`:
- **REPRICE** if `p* ≤ p_current − max(2%, $3)` and the last reprice was ≥ R hours ago, `R = max(1h, τ_total / 12)`. Hysteresis stops flapping.
- The list price never goes up while LIVE. Only a seller command (new floor or deadline) re-plans from scratch.
- Every REPRICE also **BROADCASTs** to the interested pool at `max(F, p* − 3%)`. That is the "sent $200 offers to 7 buyers" beat. Broadcast offers expire after `min(6h, τ/4)`.

## Endgame
`τ_esc = max(2h, 5% of the original horizon)`.
- If `τ ≤ τ_esc`, there is no executable offer ≥ F, and we have not escalated yet: **ESCALATE** once. The text shows the best real offer, the floor, and three replies: take it / wait / extend.
  - "take it" → the seller has lowered the floor to that offer (the ledger records the seller message as the source) → ACCEPT
  - "wait" → continue · "extend to tue" → new deadline → re-plan
- If `τ ≤ 0`: **ROUTE_INSTANT** if instant is allowed and pre-authorized, else **EXPIRE** with a summary and the standing offers.

## Closing
ACCEPT → ISSUE_CHECKOUT(b, amount) → status PENDING_PAYMENT.
Payment window `W = clamp(τ/4, 15 min, 24h)` in simulated time. Stripe's own session expiry minimum is 30 real minutes; the engine's window is enforced by us and the guard expires the Stripe session when the window closes or the payment fails.
- paid (verified webhook, amount ≥ agreed) → SOLD → BUY_LABEL → SCHEDULE → seller summary with the counterfactual against S
- failed or expired → `buyer.failed_count += 1`, `r_b` halves, status LIVE, immediate re-evaluation: best remaining executable offer ≥ F → ACCEPT it (that buyer is asked "still want it at $198? here's the link") · else continue in the market

## Fee models (fees.py)
| Channel | Fee | Shipping | Settlement s_b | Default r_b |
|---|---|---|---|---|
| ebay | 13.25% + $0.30 | label at cost if listed with free shipping | 3 to 5 days | 0.97 |
| local via Stripe | 2.9% + $0.30 | 0 for pickup, label at cost if shipped | minutes | 0.85 |
| instant | 0 | prepaid | instant | 1.00 |

Instant quote (modeled, disclosed in the brief): `0.72·M` for electronics, `0.60·M` for everything else, floored at $20.

## decide(), in pseudocode
```python
def decide(s: ItemState, now) -> Action:
    tau = hours_until(s.deadline_at, now)

    if s.status == PENDING_PAYMENT:
        if now >= s.checkout.window_ends_at:
            return PaymentTimeout(s.checkout)          # guard expires the Stripe session, back to LIVE
        return Hold()

    if s.status not in (LIVE, ESCALATED):
        return Hold()

    if tau <= 0:
        return RouteInstant() if (s.instant_ok and s.instant_preauth) else Expire()

    p_star = argmax_price(s, tau)                      # grid search over V(p, tau)
    standing = [o for o in s.offers if o.open and not o.buyer.failed]
    best = max(standing, key=lambda o: ev_accept(o, s, tau), default=None)

    if best and best.amount >= s.floor and ev_accept(best, s, tau) >= v(p_star, tau, s):
        return Accept(best)

    for o in unanswered(standing):
        return Counter(o, counter_price(o, s, tau, p_star))

    if tau <= tau_esc(s) and s.status == LIVE and (best is None or best.amount < s.floor):
        return Escalate(best)

    if should_reprice(s, p_star, now):
        return Reprice(p_star, broadcast_to=interested(s), broadcast_price=max(s.floor, p_star * 0.97))

    return Hold()
```
`argmax_price`, `ev_accept`, `v`, `counter_price`, `tau_esc`, and `should_reprice` are pure functions in `engine/demand.py` and `engine/policy.py`. None of them touch I/O or the wall clock.

## Worked example (the pitch numbers; the sim regenerates them)
Sony WH-1000XM5, condition B. Comps median $223 → M = $205, σ = $25, F = $170, deadline 72h. Priors: a_local 2/day, a_ebay 4/day. S = $148.

| τ | evidence | a_local, a_ebay per day | p* | P(τ, p*) | action |
|---|---|---|---|---|---|
| 72h | none yet | 2.0, 4.0 | $222 | 0.87 | list at $222 · frontier: $148 now / ~$186 today / ~$205 in 3 days |
| 48h | 11 views, 0 inquiries in 24h | 1.3, 2.5 | $210 | 0.71 | reprice to $210 · broadcast $204 to 7 interested |
| 8h | offer $187 local, r = 0.85 | 1.1, 2.0 | $196 | 0.31 | EV_acc ≈ 0.85·181 + 0.15·V(…) ≈ $163 > EV_cont ≈ $118 → accept $187 |
| 7.7h | payment failed | | | | expire session · re-evaluate · standing $198 buyer from 9h → accept · new pay link |
| 7.5h | paid | | | | SOLD $198 · label · calendar · "$50 more than the instant option" |

The exact figures come from `sim/run.py` and `tests/test_policy.py`. The table is the shape the ledger must reproduce.

## Why this holds up in front of judges
- Every number in a text traces to a ledger row: inputs (M, σ, F, τ, a_c, standing offers), the grid argmax with its top candidates, and the comparison that picked the action.
- Four parameters per channel, priors in one file, no hidden tuning.
- The same `decide()` runs in real time, in the accelerated demo, and across 2,400 simulated markets. If it is wrong, the sim finds it before the judges do.
