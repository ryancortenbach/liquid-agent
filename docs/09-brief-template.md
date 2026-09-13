# Liquid · System and reliability brief

Submission document. Two pages. Fill the brackets from the ledger and the eval run.

## What it does
Take a picture, set a deadline, and Liquid sells the item for the most money that clears before the deadline. It lives in iMessage. It identifies the item, estimates liquidity across exits, reprices and negotiates as time runs down, takes payment, buys the label, and books the drop-off.

## Why it is different
Marketplaces optimize listings. Liquid optimizes liquidation. At every tick it maximizes P(sale before deadline) × net proceeds over price and channel, subject to the seller's floor and one sale only.

## System
- Interface: iMessage via BlueBubbles on a Mac, dedicated Apple ID
- Core: deterministic engine `decide(state, now) → action`, a guard for invariants, an outbox for side effects, one clock
- Apps: eBay (comps, listing), Stripe (payment), Shippo (label), Google Calendar (drop-off), Claude (vision, intent, negotiation text)
- Diagram: [paste from docs/02-architecture.md]

## The engine in five lines
[paste the demand model, objective, price rule, offer rule, and endgame from docs/03-engine.md]

## Invariants enforced in code
[I1 to I10 from docs/05-reliability.md, one line each]

## How we know it works
- Simulation: [table from docs/eval/results.md], [N] runs, [0] invariant violations
- Property tests: [N] random event sequences, invariants I1 to I10 hold after every step
- Webhook tests: duplicates, forged signatures, out-of-order events
- LLM evals: vision top-1 [x/20], intent exact match [x/30], leaks [0/100]
- Live run: the demo video was recorded unattended in demo mode; the ledger is attached as `docs/eval/demo-ledger.json`

## Failure handling
- Payment failure → session expired, buyer dropped, next best executable exit taken (shown in the demo)
- Adapter outages → outbox retries with backoff; comps fall back to a low-confidence estimate; Stripe polling if webhooks stall
- Process restart → nothing lost, nothing duplicated (outbox plus webhook receipts)

## What is real and what is modeled
[table from docs/05-reliability.md]

## Limitations
- Sold-price data is modeled from active asks
- eBay listing is sandbox only
- One item per seller at a time
- The instant liquidation quote is modeled, not a partner

## Run it
```
cp .env.example .env            # fill keys
uv sync && uv run uvicorn app.main:app
uv run python scripts/smoke_all.py
uv run pytest
uv run python sim/run.py && uv run python sim/report.py
```
