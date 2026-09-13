from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.listing.draft import ListingDraft
from app.models import Item, ListingPack, ListingPackStatus
from app.pricing.schedule import PriceSchedule


def replace_draft_packs(
    session: Session,
    *,
    item: Item,
    draft: ListingDraft,
    schedule: PriceSchedule,
    platforms: list[str],
    photo_ids: list[str],
    sources: list[dict[str, Any]],
) -> list[ListingPack]:
    """Rebuild the per-channel draft packs for an item (older drafts are replaced)."""
    for stale in session.exec(
        select(ListingPack).where(
            ListingPack.item_id == item.id, ListingPack.status == ListingPackStatus.DRAFT
        )
    ).all():
        session.delete(stale)
    packs: list[ListingPack] = []
    for channel in platforms:
        pack = ListingPack(
            item_id=item.id,
            channel=channel,
            title=draft.title,
            description=draft.description,
            price_cents=schedule.list_price_cents,
            condition=draft.condition,
            specifics_json={key: value[0] for key, value in draft.aspects.items()},
            photo_ids_json=list(photo_ids),
            schedule_json=[step.as_dict() for step in schedule.steps],
            sources_json=list(sources),
        )
        session.add(pack)
        packs.append(pack)
    session.flush()
    return packs
