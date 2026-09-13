# Build status

Updated 2026-09-13.

## Green now

- Seller-only product model with no checkout or payment processing
- OpenAI product-photo edit adapter using the high-precision image model
- Studio, natural-home, and clean-tabletop photo presets
- Immutable original photo storage with MIME and file-signature validation
- Local HEIC decoding and EXIF orientation normalization for iPhone photos
- Generated photo records containing the source link, hash, model, prompt, preset, and disclosure
- Mandatory seller review before an enhanced image can join the listing image set
- Authenticated BlueBubbles webhook with sender allowlisting and event deduplication
- Complete iMessage photo intake, enhancement preview, approval, rejection, and status flow
- SQLite sale claims that pause duplicates and support confirmed or failed marketplace closes
- Deadline pricing engine, guard, ledger, outbox, simulation, and evaluation artifacts
- FastAPI item, photo enhancement, photo review, file, planning, tick, and ledger endpoints
- 38 passing unit, API, property, clock, simulation, sale-claim, photo, and iMessage tests

## Ordered P0 queue

1. Add product identity and defect extraction before image editing.
2. Add automated comparison checks between original and generated images.
3. Complete a live BlueBubbles and OpenAI smoke test after credentials are configured.
4. Publish approved listing packs to the eBay sandbox.
5. Build the assisted Facebook Marketplace publication flow.
6. Add the outbox delivery worker and restart tests.
7. Build the demo dashboard and recorded scenario.

## Local setup blockers

- `OPENAI_API_KEY` is required for a live photo edit.
- BlueBubbles needs manual installation and macOS permissions.
- eBay sandbox keys and seller authorization are required for a live sandbox listing.
- Google Calendar OAuth is optional and not yet configured.

These do not block local tests or development with a fake photo editor.
