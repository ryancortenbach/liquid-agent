# 06: The two-minute demo

One seller, one item, one weak photo, one listing pack, and one cross-channel sale.

## Screen layout

- Left: the seller's iPhone through iPhone Mirroring.
- Right: Liquid showing the original and enhanced photos, seller approval, marketplace status,
  countdown, and decision ledger.

## Script

| Time | What happens |
|---|---|
| 0:00 | Seller sends a dark, cluttered photo of Sony headphones and says, `sell these by Sunday at 6. do not go under 170.` |
| 0:12 | Liquid identifies the item and asks for one extra angle that clearly shows the headband scuff. |
| 0:24 | Liquid shows the untouched originals beside an AI-enhanced studio set. Lighting and background improve, while the scuff, labels, color, proportions, and included accessories remain unchanged. |
| 0:40 | Seller approves the image set and listing copy. Nothing publishes before this approval. |
| 0:52 | Liquid publishes the eBay sandbox listing and prepares the Facebook Marketplace listing for seller-assisted publication. |
| 1:08 | Demand is weak, so Liquid reprices within the seller's floor and explains why. |
| 1:22 | A Facebook buyer agrees, so Liquid records a sale claim and pauses the other listings. The buyer backs out, so Liquid releases the claim and resumes them. |
| 1:38 | An eBay order arrives. Liquid marks the item sold, ends the other listings, and schedules fulfillment. |
| 1:50 | Show the evaluation table, photo-truth checks, and zero double-sale violations. |

## What judges must understand

1. Only sellers use Liquid.
2. A normal phone photo becomes a professional but truthful listing asset.
3. Originals are immutable and every generated image requires seller approval.
4. Buyers remain on eBay, Facebook Marketplace, and other existing channels.
5. Liquid coordinates pricing, offers, and listing state. It never processes payment.

## Fallbacks

- If live image editing is unavailable, replay a recorded API response and disclose it.
- If BlueBubbles is unavailable, upload the same photo through the FastAPI demo page.
- If eBay is unavailable, use the sandbox response fixture and keep the assisted Facebook flow.
- Record a complete take before judging and use the live system for questions.
