# 00 · The brief, the rubric, and how we score

Source: https://multiappagenthackathon.com and /judges (read 2026-09-12).

## Event
- Multi-App AI Agent Hackathon · virtual · Sunday, September 13, 2026 · all times Pacific
- 9:00 opening · 9:30 to 16:00 build · 16:00 to 16:40 judging and selection · 16:40 to 17:00 awards
- Hosted by Lemma and a second sponsor. Judged by the founders of Userlens (Ankur Dahama, Hai Ta) and Arga Labs (Phillip Li, Akira Tong).
- Prizes: $10,000 / $4,000 / $1,000. Every top-three team gets interviews with Arga Labs or Lemma AI.
- Teams of one to four.

## The brief, verbatim
> Build one useful, multi-step AI agent. Connect it to at least three external apps. Show how you know it works.

## What we submit
1. Working project or repository (this repo)
2. Two-minute demo (docs/06-demo.md)
3. Short system and reliability brief (docs/09-brief-template.md, filled in during the day)

## Rubric, and what earns each line
| Weight | Criterion | What earns it for us | Where it lives |
|---|---|---|---|
| 30% | Technical execution | A real decision engine (pricing under time pressure, routing, negotiation), five live integrations, a concurrency-safe payment flow, a real iMessage bridge | docs/03, docs/04 |
| 25% | Reliability & evaluation | Hard invariants enforced in code, a simulation harness with numbers, property tests, chaos tests, a decision ledger, honest "real vs modeled" table | docs/05 |
| 20% | Usefulness | A problem everyone has (stuff to sell, a date it has to be gone by), zero marketplace knowledge required, no app to open | docs/01 |
| 15% | Originality | Liquidity routing instead of listing generation. "Set a deadline, not a price." The liquidity frontier. | docs/01, docs/03 |
| 10% | Demo clarity | One item, one deadline, one failure, one recovery, 120 seconds | docs/06 |

Execution and reliability together are 55%. The eval harness and the brief are first-class deliverables, not extras. Build the clock abstraction and the ledger in the first hour; everything the judges score depends on them.

## The "show how you know it works" answer, in one paragraph
We run the agent against a seeded simulated market (Poisson buyer arrivals, noisy willingness to pay, ghosts, payment failures) across deadlines of 12h, 24h, 72h, and 7d and 200 seeds each, and compare realized net proceeds against a static listing, a linear markdown schedule, and an oracle upper bound. We property-test the invariants over random event sequences (never below floor, never sold twice, never sold unpaid, never after deadline). We replay duplicate and out-of-order webhooks. Every live decision writes a ledger row with its inputs, so any outcome in the demo can be explained from the numbers.

## External apps (minimum is three, we connect five plus Claude)
| App | Role | Real in demo? |
|---|---|---|
| iMessage (BlueBubbles on a Mac) | Seller and buyer conversations | Yes |
| eBay | Comps via Browse API; listing via Sell API in sandbox (P1) | Comps yes, listing sandbox |
| Stripe | Buyer payment, payment-failure signal | Yes, test mode |
| Shippo | Shipping rates and label | Yes, test mode |
| Google Calendar | Drop-off / pickup event | Yes |
| Claude | Vision, intent parsing, comps filtering, negotiation drafting, seller voice | Yes |
