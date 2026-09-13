# Liquid: System and reliability brief

## What it does

Liquid turns an ordinary seller's phone photos into truthful, professional listing assets and
coordinates the sale across existing marketplaces before the seller's deadline.

## Product boundary

Only sellers use Liquid. Buyers stay on eBay, Facebook Marketplace, Craigslist, OfferUp, and other
channels. Liquid is not a marketplace, checkout, escrow, or payment processor.

## System

- Seller interface: iMessage through BlueBubbles
- Photo editing: OpenAI Image API with immutable originals and seller review
- Core: deterministic deadline engine, invariant guard, ledger, and transactional outbox
- Channels: eBay official APIs and seller-assisted marketplace publication
- Fulfillment: marketplace tools first, optional Shippo and Google Calendar

## Photo truth contract

- Improve only lighting, background, framing, and color balance.
- Preserve identity, geometry, color, labels, serial numbers, damage, wear, and accessories.
- Keep the original and generated files, hashes, model, prompt, and review state.
- Never publish a generated image before the seller approves it.

## Evidence

- Simulation: paste the table from `docs/eval/results.md`.
- Tests: insert total passing tests and invariant count.
- Photo checks: show original and approved output pairs with the known defects visible.
- Demo ledger: attach the recorded item ledger.

## Limitations

- Generated image fidelity still requires human review.
- eBay listing publication is sandbox-only for the demo.
- Facebook Marketplace, Craigslist, and OfferUp publication is seller-assisted.
- Marketplace payments remain outside Liquid.
