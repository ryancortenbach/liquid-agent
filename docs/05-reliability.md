# 05: Reliability and evaluation

## Invariants

| # | Invariant |
|---:|---|
| I1 | No list, counter, broadcast, or accepted marketplace price is below the seller floor without seller approval. |
| I2 | At most one ACTIVE sale claim exists per item. SOLD is terminal. |
| I3 | No offer is accepted after the deadline. |
| I4 | SOLD requires a trusted marketplace event or explicit seller confirmation. |
| I5 | Creating a sale claim pauses every competing listing. Confirming a sale ends them. Releasing a failed claim resumes eligible listings. |
| I6 | Every side effect has an idempotency key. Every marketplace event id is processed once. |
| I7 | Every action and rejected action writes a ledger event with its inputs and reason. |
| I8 | The floor changes only from a seller instruction. |
| I9 | Marketplace replies never reveal the floor, deadline pressure, or another buyer's offer. |
| I10 | A live price never increases without an approved seller replan. |
| I11 | Enhanced photos preserve damage, color, proportions, labels, and included accessories. |
| I12 | Assisted channels require the seller's final publication approval. |

## Concurrency and idempotency

Ticks, marketplace events, and seller commands take the same per-item lock. Under that lock, the
executor writes the state transition, sale claim, ledger event, and outbox rows in one transaction.

The database has a partial unique index on ACTIVE sale claims. Even if application locking fails,
two channels cannot claim the same item concurrently. Duplicate marketplace events are ignored by
provider and event id. An event received after SOLD cannot change the winner or amount.

## Photo truth

Original files are immutable. Enhanced assets are separate and retain a transformation record.
Tests compare identity features and condition evidence. A questionable edit is rejected and the
original is used. The seller preview shows the final image set and condition copy before assisted
publication.

## Evaluation harness

The seeded simulator covers Poisson arrivals, noisy willingness to pay, lowballs, buyer withdrawal,
no-shows, marketplace fees, and deadline pressure. It compares the real engine with static list,
static 90 percent, linear markdown, and an oracle upper bound.

Metrics:

- Mean net proceeds
- Marketplace sale rate before the deadline
- Instant exit rate
- Regret against the oracle
- Seller interruptions
- Invariant violations, which must remain zero

The initial harness has 12,000 policy runs across four deadlines and three item archetypes. Response
latency and delayed settlement remain explicit simulation limitations.

## Tests

- Property tests for floor, deadline, and price invariants
- Database test for the single ACTIVE sale claim
- Accept, confirm, release, pause, end, and resume transition tests
- Duplicate and out-of-order marketplace event tests
- Adapter retry and restart tests
- Photo truth and listing-copy evaluation sets
- Seller intent tests with fixed time and timezone

## Real and modeled

| Component | Status |
|---|---|
| Seller iMessage intake | Real after BlueBubbles setup |
| Item and photo analysis | Real model calls with deterministic fallback |
| eBay comps | Real Browse API |
| eBay listing | Sandbox for demo, production only with seller approval |
| Facebook Marketplace | Assisted seller flow |
| Craigslist and OfferUp | Assisted seller flow |
| Buyer demand in demo | Seeded simulation plus any real marketplace signals |
| Marketplace payment | Handled by the marketplace or buyer and seller, never Liquid |
| Instant quote | Modeled until a real partner is connected |
| Shipping label | Marketplace label or Shippo test label |
| Calendar event | Real |

## Definition of green

From a clean database, seller photos and a deadline produce truthful listing assets, comps, a
channel plan, an eBay sandbox listing, and a seller-approved Facebook Marketplace draft. The demo
shows a reprice, a marketplace offer, one active sale claim, a failed close that safely resumes all
channels, a confirmed sale that ends every competing listing, and zero invariant violations.
