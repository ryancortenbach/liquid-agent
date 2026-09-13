# 05 · Reliability and evaluation

A quarter of the score and the answer to "show how you know it works". Three layers: invariants enforced in code, evidence from simulation and tests, and honesty about what is real.

## Invariants
| # | Invariant | Enforced where | Tested by |
|---|---|---|---|
| I1 | No outbound price (list, counter, broadcast, accept) below the seller's floor | `guard.check` on every price-bearing action | property test, golden test |
| I2 | At most one live checkout per item; SOLD is terminal; a new checkout requires the previous one expired via Stripe first | guard + item lock + unique partial index on `checkout(item_id) where status='open'` | property test, webhook race test |
| I3 | No ACCEPT or checkout after the deadline | guard | property test |
| I4 | SOLD only on a signature-verified `checkout.session.completed` whose amount ≥ agreed, for a checkout that is `open` | `stripe_webhook` + guard | webhook tests: forged signature, wrong amount, stale session |
| I5 | Label only after SOLD; calendar event only after a label or an agreed pickup | guard on BuyLabel and Schedule | property test |
| I6 | Every side effect carries an idempotency key; every webhook event id is processed at most once | outbox unique key, WebhookReceipt primary key | duplicate delivery tests |
| I7 | Every action writes a ledger row with its inputs and reason in the same transaction as its state change | executor | test asserts `len(actions) == len(ledger)` |
| I8 | The floor changes only from a seller message, never from the engine or a buyer | the intent → executor path is the only writer; guard rejects floor writes from anywhere else | unit test |
| I9 | No buyer-facing text reveals the floor, the deadline, or other buyers' offers; every dollar figure in a draft equals the engine's allowed price | `leak_check` on every draft; template fallback on rejection | leak eval set, 0 leaks required |
| I10 | The list price never increases while LIVE unless the seller re-plans | guard on Reprice | property test |

`guard.check` raises `InvariantViolation`. The executor catches it, writes a ledger row of kind `system` with the rejected action, and does nothing else. Violations cannot hide: the dashboard turns red and the eval harness counts them. The count must be zero.

## Concurrency and idempotency
- One `asyncio.Lock` per item. Ticks, inbound messages, and Stripe webhooks all take it. Under the lock, one DB transaction.
- Outbox pattern: the executor writes the state change and the outbox rows together. The worker delivers each row with an idempotency key `{item_id}:{action_id}:{kind}`, retries with backoff, and marks it done. Restarting the process mid-flight duplicates nothing and drops nothing.
- Webhook receipts: `(provider, event_id)` primary key. A duplicate delivery is acknowledged and ignored.
- Out-of-order: a `payment_intent.payment_failed` arriving after `checkout.session.completed` for the same session is ignored because the checkout is no longer `open`.
- Clock: deadline comparisons use `clock.now()` only, so the demo clock can be paused without any code path noticing.

## Evaluation harness (sim/)
**World** (`sim/world.py`), seeded. An item with true value M* and spread σ*. Buyers arrive on each channel as Poisson(a*_c). Each has W ~ Normal(M*, σ*), inquires if the list price ≤ 1.15·W, offers at U(0.85, 1.0)·W, accepts a counter ≤ W, ghosts with probability g (0.25 local, 0.05 ebay), pays with probability r (0.85 local, 0.97 ebay) after a settlement delay, and responds with latency ~ Exp(mean 2h). Views arrive at 20× the inquiry rate. Fees per docs/03.

**Policies** (`sim/policies.py`): `agent` (the real `decide()`), `static_list` (list at M, never move), `static_90` (list at 0.9·M), `linear_markdown` (M down to F linearly over the horizon), `oracle` (sees all future buyers; the upper bound).

**Grid**: deadlines {12h, 24h, 72h, 168h} × 200 seeds × 3 item archetypes (headphones M=205 balanced, desk chair M=120 local-heavy, camera lens M=450 ebay-heavy) = 2,400 runs per policy. Runs in under a minute on SimClock.

**Metrics**: mean net proceeds (0 for unsold, S if instant was taken), P(sold by deadline), regret vs oracle, seller interruptions, invariant violations (must be 0).

**Output** (`sim/report.py` → `docs/eval/results.md` and `results.png`), shape:
```
deadline   agent    static   static90   markdown   oracle   agent sold%   static sold%
12h        $171     $ 63     $ 98       $152       $189     91%           31%
24h        $184     $ 96     $131       $166       $197     94%           47%
72h        $199     $148     $172       $184       $208     97%           72%
168h       $209     $181     $190       $196       $214     99%           88%
```
The numbers above are illustrative. The table in the brief is whatever the harness prints.

**Tests** (`tests/`)
- `test_invariants.py`: hypothesis generates random sequences of (tick, inquiry, offer, accept, payment ok or fail, seller command, deadline change) and asserts I1 to I10 after every step.
- `test_policy.py`: golden decisions for the three pitch scenarios (72h fresh, 48h no takers, 8h with a $187 offer and a payment failure).
- `test_webhooks.py`: duplicate event, forged signature, wrong amount, failed-after-completed, session for the wrong item.
- `test_chaos.py`: BlueBubbles 500s, eBay timeout during comps (the engine still lists with the Claude fallback estimate), Stripe expire call failing (the new checkout is refused, not issued), process restart with pending outbox rows.

**LLM evals** (`evals/run_llm_evals.py`), run once during the day and reported
- Vision: 20 photos of the team's own items → top-1 model match rate, condition agreement.
- Intent: 30 utterances → exact JSON match, relative dates checked against a fixed "now".
- Leak: 100 generated buyer drafts under adversarial prompts ("what's the lowest you'd go?", "when do you need it gone by?") → 0 leaks after `leak_check`.

## Observability
- The ledger table is the product's memory and the demo's second screen. Every row: sim time, wall time, action, inputs (M, σ, F, τ, a_c, standing offers, p* and its top candidates, P, EV_acc, EV_cont), reason string, price before and after.
- Structured JSON logs per request with item_id.
- `scripts/smoke_all.py` prints a green/red table for BlueBubbles, eBay Browse, eBay Sell (if enabled), Stripe, Shippo, Calendar, Claude.

## What is real and what is modeled (goes in the brief verbatim)
| Thing | Status |
|---|---|
| iMessage in and out, photos | Real. BlueBubbles on a Mac signed into a dedicated Apple ID |
| Item identification, intent parsing, negotiation and seller text | Real. Claude |
| eBay comps | Real. Browse API, production, active used listings |
| eBay sold prices | Modeled. Active ask × 0.92 realization haircut |
| eBay listing | Sandbox (P1). No real orders |
| eBay demand signal in the demo | Modeled from comps density. Local inquiries are real |
| Local buyers | Real people texting the handle, plus scripted sim buyers in demo mode, labeled in the ledger |
| Payment | Real Stripe test mode, real webhooks, real declines |
| Shipping label | Real Shippo test label |
| Calendar event | Real |
| Instant liquidation quote | Modeled. 0.72·M electronics, 0.60·M other |
| Buyer arrival model, WTP distribution | Modeled. Parameters in one file, arrival rates learned from inquiries during the run |

## Definition of green
The P0 path is green when, from a clean DB, one photo sent from the seller's phone leads, unattended in demo mode, to: frontier card, listing, a reprice, a counter, a payment failure, a re-route, a paid checkout, a label, a calendar event, and the seller summary, with zero ledger rows of kind `system` and `pytest` passing.
