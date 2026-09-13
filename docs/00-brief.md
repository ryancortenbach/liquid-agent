# 00: The brief, the rubric, and how we score

Source: https://multiappagenthackathon.com and `/judges`, read 2026-09-12.

## Event

- Multi-App AI Agent Hackathon, virtual, Sunday, September 13, 2026, all times Pacific
- 9:00 opening, 9:30 to 16:00 build, 16:00 to 16:40 judging, 16:40 to 17:00 awards
- Teams of one to four

## Brief

> Build one useful, multi-step AI agent. Connect it to at least three external apps. Show how you
> know it works.

## What we submit

1. Working repository
2. Two-minute demo from `docs/06-demo.md`
3. Short system and reliability brief from `docs/09-brief-template.md`

## Product boundary

Liquid is only for sellers. It is not a marketplace, checkout product, escrow service, or buyer
app. Buyers remain on the marketplaces they already use. Liquid improves photos and listing
quality, publishes through official APIs or seller-approved assisted flows, manages pricing and
offers, and keeps inventory synchronized across channels.

## Rubric strategy

| Weight | Criterion | What earns it for us |
|---:|---|---|
| 30% | Technical execution | Real eBay listing flow, assisted Facebook Marketplace flow, deadline pricing, cross-channel sale claims, and marketplace adapters |
| 25% | Reliability and evaluation | Hard invariants, simulation, property tests, duplicate marketplace-event tests, photo-truth checks, and a decision ledger |
| 20% | Usefulness | A regular person gets credible photos and listings without learning each marketplace |
| 15% | Originality | Deadline-native routing and repricing across existing marketplaces |
| 10% | Demo clarity | One item, one deadline, one weak photo set, one failed close, one recovery |

## How we know it works

We run the engine against seeded markets across 12-hour, 24-hour, 72-hour, and 7-day deadlines.
We compare realized proceeds with static and linear-markdown policies. We property-test the floor,
deadline, monotonic-price, single-sale-claim, and terminal-sale invariants. We replay duplicate and
out-of-order marketplace events. Every decision records its inputs in a ledger. Photo tests verify
that enhancements improve presentation without hiding damage, changing color, or inventing
included accessories.

## External apps

| App | Role | Demo mode |
|---|---|---|
| iMessage through BlueBubbles | Seller intake, approval, and status | Real when local setup is complete |
| eBay | Comps and listing | Real Browse API, sandbox listing |
| Facebook Marketplace | High-demand local channel | Seller-approved assisted publishing |
| Google Calendar | Pickup or shipping reminder | Real |
| Shippo | Label only when the marketplace does not provide one | Test mode |
| Claude | Identification, photo review, listing copy, intent, and explanations | Real |
