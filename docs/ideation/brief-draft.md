# Liquid · system and reliability brief · draft v1 (03:52 EDT)

Two pages when set. Numbers marked ⟦pre-registered⟧ are the expectations written before the build (`docs/ideation/preregistration.json`, sha256 874acade…bb80c); replace with Sunday's realized values and report every miss.

## What it does
Text a photo and a deadline to an iMessage contact. Liquid identifies the item (and asks when the model is ambiguous), tells you what it is worth now versus by your deadline, then sells it for the most money that actually clears in time: it lists, reprices as time passes and evidence arrives, negotiates offers, routes to the best executable exit, takes payment, dispatches a courier, and books the pickup on your calendar. It never goes below your floor, never sells twice, and never says "sold" before the money has cleared.

## Why it is different
Marketplaces optimize listings. Liquid optimizes liquidation. The seller chooses a point on a **liquidity frontier** ("$221 guaranteed now · ~$290 likely today · ~$305 likely by Sunday") instead of guessing a price, and the engine moves along it as the deadline approaches. The honest edge, as a pre-registered expectation from our twin (realized values replace these on Sunday): at one day the product's value is mostly certainty (⟦+$19⟧ over an eBay Best Offer proxy); at three days ⟦+$43⟧; at a week ⟦+$59⟧, before a 5% take.

## System
- **Interface**: iMessage through a BlueBubbles bridge on a Mac signed into a dedicated Apple ID. Real blue bubbles, photos in, texts out.
- **Core**: a deterministic engine, `decide(state, now) → action`, with no I/O and no wall clock inside it. The language model identifies items, parses intent, filters comps, and drafts text; it never sets a price or moves money.
- **Guard**: every action passes fourteen invariants before any side effect. Side effects go through an outbox with idempotency keys.
- **Apps, all real**: eBay Browse (comps, production) and an unpublished draft offer carrying the floor as `autoDeclinePrice`; Stripe Checkout in test mode with real webhooks and real declines; DoorDash Drive sandbox with simulator webhooks; Google Calendar; Claude.
- **Clock**: one injectable clock runs real time, the accelerated demo, and the twin through identical code.

## The engine in five lines
```
q(p)    = 1 − Φ((p − M)/σ)                          share of buyers who pay p; σ from the comps' robust dispersion
λ_c(p)  = a_c · q(p)                                a_c learned online, Gamma-Poisson (Aviv & Pazgal 2005)
V(τ)    = max_p [ (1 − e^{−λ(p)Δ}) n̄(p) + e^{−λ(p)Δ} V(τ−Δ) ],  V(0) = instant quote   (Gallego & van Ryzin 1994)
accept an offer o  iff  o ≥ floor and net(o) ≥ V(τ)                              (Karlin 1962; McCall 1970)
frontier = realized outcomes of that policy in the twin, with their probabilities   (Almgren & Chriss 2000, relabeled)
```

## Failure modes and catches
The Guard checks against named failure classes, not one price rule. Classes follow Lemma's taxonomy; one test per class; two are caught on screen in the demo.
| Class | The failure | The catch | Test |
|---|---|---|---|
| Instruction Violation | a drafted counter below the seller's floor; a draft that reveals the floor under adversarial questioning | I1 floor check and leak check on every draft; template fallback | `test_invariants.py`, `evals/run_llm_evals.py` (⟦0/100⟧ leaks) |
| Hallucination | a confident item id that is wrong, so every later step is "correct" on the wrong value | I12: ≥8 cleaned comps and agreement within 15% of the comps median with an independent price prior, else the seller confirms | `test_policy.py::test_value_sanity` |
| Integration Failure | a decline after acceptance; a comps timeout | reroute to the next executable buyer on the ledger; labeled fallback estimate | `test_webhooks.py`, `test_chaos.py` |
| Skipped Work | "it's up" texted, listing never happened | no outbound claim without a done outbox row with an external id | `test_skipped_work` |
| Out of Scope Work | a label bought for a local-only sale | I14: seller constraints enforced on every fulfillment action | property test |
| Retry Loop | the bridge is down and retries multiply | backoff capped at six attempts, dead-letter, DELIVERY_STALLED row; idempotency keys make recovery duplicate-free | `test_chaos.py` |
| Communication Failure | a number in a text that the ledger never produced; "sold" before SOLD | every figure in outbound text must exist in the producing ledger row | `test_communication` |
| (unnamed) model divergence | every step legal, the world model wrong | I13: posterior predictive check on inquiries each tick → MODEL_DRIFT row, prior widened | `test_drift` |
| crashes | restart with pending side effects | outbox plus webhook receipts: nothing lost, nothing duplicated | `test_chaos.py::test_restart` |

## Twin, not mock: what the simulator reproduces
The eBay sandbox is a stateless mock with no buyers, so the market the engine trades against is a stateful twin: seeded Poisson arrivals per channel, willingness to pay with the comps' dispersion, buyers who counter at 85 to 100% of their value, ghost 30% of the time after a counter, and fail payment (10% local, 3% marketplace), with fees, settlement delays, duplicate and out-of-order webhooks. The same twin (a) prices each item at intake with 1,000 runs, (b) runs the eval grid on every commit, and (c) drives the "same buyers, three sellers" race on the dashboard under common random numbers.

## Cross-system identity resolution
One person can text the agent, click "buy now" on the offer page, and pay under a third identifier. I11 resolves identity across iMessage handle, offer-page email, and Stripe customer before a lead is counted, or the arrival rate inflates and two checkouts can reach one human. Implemented and unit-tested (`test_identity.py`); not demonstrated with two phones in the video.

## Invariants
I1 no outbound price below the floor · I2 one live checkout per item, SOLD terminal, expire before reissue (unique partial index) · I3 nothing after the deadline · I4 SOLD only on a verified payment ≥ agreed · I5 label or courier only after SOLD · I6 idempotency keys and webhook receipts · I7 a ledger row per action in the same transaction · I8 the floor changes only from a seller message · I9 no leaks and every figure equals the allowed price · I10 the price never rises while live · I11 identity resolved before counting · I12 value sanity before listing · I13 model drift detected at runtime · I14 seller constraints enforced on fulfillment.

## How we know it works
- **Pre-registered expectations vs realized** (twin, 3,200 runs per policy, four deadlines, four archetypes): ⟦table⟧; the envelope predicts a 72h mean net of $306, sold 100%, edge over the Best Offer proxy +$43, DP-vs-twin gap +$2; realized values go here.
- **Sensitivity**: value ±10%, arrivals ±50%, σ ∈ {20, 35, 50}, payment failures 15% → ⟦table⟧; floor breaches 0 in every cell.
- **External calibration**: ⟦20⟧ hand-collected sold prices across three archetypes → value estimate off by a median of ⟦x%⟧. Observed instant ratio for the demo item 0.73 (a 27% discount) vs the modeled 0.72.
- **Property tests** over random event sequences: I1 to I14 hold after every step (⟦N⟧ examples).
- **Webhook tests**: duplicates, forged signatures, wrong amounts, failed-after-completed.
- **Red team**: 30 Claude buyer personas negotiate against the policy; ⟦0⟧ floor leaks; realized price vs oracle ⟦x%⟧.
- **Recorded run, demo mode**: the video was recorded in demo mode; the ledger is attached as `docs/eval/demo-ledger.json` with REAL/TWIN badges per event.

## What is real, what is twin, what is decision-ready
| | |
|---|---|
| Real | iMessage in and out; Claude identification and text; eBay comps (production); Stripe test mode with real webhooks and declines; DoorDash Drive sandbox dispatch and status webhooks; Google Calendar events |
| Twin | buyers, unless a teammate is texting (every ledger event says which); marketplace demand signal |
| Modeled | sold prices (active asks × 0.92); the instant quote is a real published offer taken by hand, not an API |
| Decision-ready | the frontier card; each check-in with its reason; the sold summary with the counterfactual |

## Where we lose
With buyers who can counter, no cell in the sensitivity sweep loses: the agent accepts anything above its continuation value, so an overestimated value gets corrected by counteroffers (value −10%: agent $284 vs static $271). With list-price-only buyers, a 10% overestimate costs $261 vs $272. We show that cell because we do not get to choose which world we are in; I12 and I13 exist for it, and the floor bounds the downside regardless.

## Limitations
One Mac and one Apple ID behind iMessage (a product would use business messaging); Stripe test mode proves the flow, not authorization, disputes, or payouts; eBay listing is a sandbox draft; one item per seller; sold-price data is modeled; priors were invented and then learned.

## Run it
```
cp .env.example .env
uv sync && uv run uvicorn app.main:app
uv run python scripts/smoke_all.py
uv run pytest
uv run python twin/run.py   # writes docs/eval/results.{csv,md,png} and the envelope diff
```
