# 01: Product spec

Name: **Liquid**. As in liquidity, turning possessions into cash on a timeline.

## One line

Take a picture. Set a deadline. Get it listed everywhere it can sell.

## Product boundary

Liquid is a seller tool for ordinary people. Buyers do not create Liquid accounts, visit a Liquid
marketplace, or pay Liquid. They see normal listings on eBay, Facebook Marketplace, Craigslist,
OfferUp, and future supported channels.

The seller sends photos and a deadline. Liquid makes the item look professionally presented while
remaining truthful, writes channel-specific listings, publishes wherever permitted, and keeps the
seller out of repetitive listing and pricing work.

## Thesis

Most people are poor marketplace operators, not poor owners of sellable things. Their photos are
dark or cluttered, their descriptions look suspicious, and they do not know which channel or price
fits the deadline. Liquid turns one casual photo set into a credible multi-channel selling campaign.

The deadline remains the decision primitive. Liquid prices for the best executable result before
the seller needs the item gone.

## Seller interface

Liquid lives in the seller's messages. Voice is lowercase, warm, and short. Numbers are exact.
The seller sees previews, approval requests, meaningful price changes, offers that require a
decision, and the final sale. Buyers interact with the native marketplace listing and messaging
experience.

## Who it is for

- Regular people moving, traveling, decluttering, or raising cash
- Sellers who do not know how to photograph, describe, price, or cross-list an item
- People worried that weak photos or copy will make a real item look fake or low quality
- Demo persona: Sam is moving and needs to sell Sony WH-1000XM5 headphones by Sunday

## Core loop

1. **Intake.** Receive photos, a deadline, a floor, and constraints from the seller.
2. **Make it credible.** Identify the item, grade condition, flag missing angles or poor lighting,
   and produce truthful listing-ready photos. Keep originals and never erase damage.
3. **Discover.** Pull comps, estimate value and spread, compute the liquidity frontier, and choose
   channels and opening prices.
4. **Publish.** Publish through official APIs where available. For assisted channels, prepare and
   fill the form, show the seller a preview, and require approval for the final publish action.
5. **Operate.** Monitor views, inquiries, offers, and order signals. Reprice, draft replies, compare
   channel offers, and ask the seller only when policy requires a decision.
6. **Close safely.** An accepted channel creates one sale claim and pauses every other listing.
   A verified marketplace order event or explicit seller confirmation marks the item sold. A
   failed close releases the claim and resumes the listings.
7. **Finish.** Use the marketplace label when available, otherwise create a Shippo label. Add the
   pickup or drop-off to the seller's calendar.

## P0 features

| # | Feature | Acceptance criteria |
|---:|---|---|
| F1 | Seller messaging | Photo and text reach the server, and replies return to the seller |
| F2 | Item identification | Title, brand, model, category, condition, confidence, and one clarification if needed |
| F3 | Intent parsing | Deadline, floor, shipping, local-only, and seller commands become validated data |
| F4 | Photo quality | Reject blurry or incomplete sets, request missing angles, create clean listing assets, preserve originals, and never alter condition evidence |
| F5 | Comps | Clean eBay Browse results produce market value, spread, and confidence |
| F6 | Liquidity frontier | Show estimated proceeds for immediate, 24-hour, 72-hour, and 7-day exits |
| F7 | Channel plan | Choose eBay, Facebook Marketplace, Craigslist, OfferUp, or a subset based on item and deadline |
| F8 | eBay publishing | Create inventory item, offer, and sandbox listing through the official API |
| F9 | Assisted publishing | Fill Facebook Marketplace listing fields and require seller approval for final publication |
| F10 | Listing pack | Channel-specific title, description, price, category, condition, attributes, and selected photos |
| F11 | Engine tick | Decide hold, reprice, broadcast, counter, accept, reroute, escalate, or expire, with a ledger row |
| F12 | Cross-channel lock | At most one active sale claim. Claiming one channel pauses every other listing |
| F13 | Sale confirmation | Only a trusted marketplace event or explicit seller confirmation can mark SOLD |
| F14 | Demo and eval | Accelerated clock, seeded markets, comparisons, and zero invariant violations |

## P1 features

- Production eBay listing after explicit seller approval
- Assisted Craigslist and OfferUp publishing
- Marketplace message drafting and reply approval
- Automatic delisting across every channel with supported APIs
- Seller commands: extend, cancel, status, change floor, accept, wait
- Pickup and shipping workflow

## Seller messages

- `[photos] sell these by sunday 6pm`
- `don't take less than $170`
- `local only`
- `use ebay and facebook`
- `make the photos look professional but don't hide the scuff`
- `extend to tuesday`
- `cancel`
- `status`

## Seller-facing examples

- Intake: `got it. sony wh-1000xm5, good condition. the first photo is dark and the headband
  scuff needs a clearer angle. send one photo from above, then i'll build the listings.`
- Preview: `listing pack is ready. 6 clean photos, ebay at $219, facebook at $210. the scuff is
  visible and described. approve both?`
- Reprice: `48h left. ebay has 31 views and facebook has 7 saves, no firm buyer. lowering both by
  $9 keeps the 72% close probability on track.`
- Offer: `facebook offer is $187 local pickup. ebay is likely worth $193 after fees but may miss
  sunday. take $187, counter $195, or wait?`
- Failed close: `the facebook buyer backed out. both listings are live again. nothing sold twice.`
- Sold: `sold on ebay for $198. the facebook listing is closed and drop-off is on your calendar.`

## Seller promises

1. We do not misrepresent the item in photos or copy.
2. We never accept below your floor without your approval.
3. We never maintain more than one active sale claim.
4. We never call it sold without a trusted marketplace signal or your confirmation.
5. We explain every price and routing decision.
6. We do not publish through an assisted channel without your final approval.

## Non-goals

- No Liquid buyer marketplace
- No Liquid checkout or payment processing
- No buyer accounts or buyer-facing app
- No unapproved browser automation
- No hidden damage removal, invented accessories, or misleading photo edits
- No production marketplace publication without explicit seller approval
