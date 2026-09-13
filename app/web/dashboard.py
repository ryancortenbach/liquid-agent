from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.models import (
    Item,
    LedgerEvent,
    ListingPack,
    PhotoRole,
    PhotoStatus,
    ProductPhoto,
    ResearchResult,
    SellerConversation,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def dollars(cents: int | None) -> str:
    return "" if cents is None else f"${cents / 100:,.0f}"


templates.env.filters["dollars"] = dollars

CONDITION_LABELS = {
    "NEW": "New",
    "LIKE_NEW": "Used, like new",
    "USED_EXCELLENT": "Used, excellent",
    "USED_VERY_GOOD": "Used, very good",
    "USED_GOOD": "Used, good",
    "USED_ACCEPTABLE": "Used, acceptable",
    "FOR_PARTS_OR_NOT_WORKING": "For parts or not working",
}

SHIPPING_LABELS = {
    "both": "Ships within one business day, or local pickup",
    "ship": "Ships within one business day",
    "pickup": "Local pickup only",
}


def condition_label(code: str | None) -> str:
    """Marketplace condition codes read badly on a page; show the buyer-facing phrase."""
    if not code:
        return "Used"
    return CONDITION_LABELS.get(code.upper(), code.replace("_", " ").capitalize())


def shipping_label(choice: str | None) -> str:
    return SHIPPING_LABELS.get((choice or "both").lower(), SHIPPING_LABELS["both"])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_index(request: Request) -> HTMLResponse:
    with Session(request.app.state.engine) as session:
        items = session.exec(select(Item).order_by(Item.created_at.desc())).all()  # type: ignore[attr-defined]
        conversations = {
            conversation.active_item_id: conversation
            for conversation in session.exec(select(SellerConversation)).all()
        }
        rows = [
            {
                "item": item,
                "conversation": conversations.get(item.id),
                "packs": session.exec(
                    select(ListingPack).where(ListingPack.item_id == item.id)
                ).all(),
            }
            for item in items
        ]
        return templates.TemplateResponse(
            request, "index.html", {"rows": rows, "clock": request.app.state.clock.now()}
        )


@router.get("/dashboard/{item_id}", response_class=HTMLResponse)
def dashboard_item(item_id: str, request: Request) -> HTMLResponse:
    with Session(request.app.state.engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        photos = session.exec(
            select(ProductPhoto)
            .where(ProductPhoto.item_id == item_id)
            .order_by(ProductPhoto.created_at)
        ).all()
        packs = session.exec(select(ListingPack).where(ListingPack.item_id == item_id)).all()
        research = session.exec(
            select(ResearchResult)
            .where(ResearchResult.item_id == item_id)
            .order_by(ResearchResult.created_at.desc())  # type: ignore[attr-defined]
        ).first()
        ledger = session.exec(
            select(LedgerEvent)
            .where(LedgerEvent.item_id == item_id)
            .order_by(LedgerEvent.sim_at.desc())  # type: ignore[attr-defined]
        ).all()
        conversation = session.exec(
            select(SellerConversation).where(SellerConversation.active_item_id == item_id)
        ).first()
        card = next(
            (row.inputs_json.get("card") for row in ledger if row.action == "listing_plan"), None
        )
        now = request.app.state.clock.now()
        hours_left = max(0.0, (as_utc(item.deadline_at) - as_utc(now)).total_seconds() / 3600)
        return templates.TemplateResponse(
            request,
            "item.html",
            {
                "item": item,
                "conversation": conversation,
                "originals": [p for p in photos if p.role == PhotoRole.ORIGINAL],
                "enhanced": [p for p in photos if p.role == PhotoRole.ENHANCED],
                "packs": packs,
                "research": research,
                "ledger": ledger,
                "card": card,
                "intake": item.constraints_json.get("intake") or {},
                "hours_left": hours_left,
                "clock": now,
            },
        )


@router.get("/demo/ebay/listings/{listing_id}", response_class=HTMLResponse)
def demo_ebay_listing(listing_id: str, request: Request) -> HTMLResponse:
    if not request.app.state.settings.ebay_demo_mode:
        raise HTTPException(status_code=404, detail="demo listings are disabled")
    with Session(request.app.state.engine) as session:
        pack = session.exec(
            select(ListingPack).where(
                ListingPack.channel == "ebay", ListingPack.external_id == listing_id
            )
        ).first()
        if pack is None:
            raise HTTPException(status_code=404, detail="demo listing not found")
        item = session.get(Item, pack.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        enhanced = session.exec(
            select(ProductPhoto)
            .where(
                ProductPhoto.item_id == item.id,
                ProductPhoto.status == PhotoStatus.APPROVED,
            )
            .order_by(ProductPhoto.created_at)
        ).all()
        originals = session.exec(
            select(ProductPhoto)
            .where(
                ProductPhoto.item_id == item.id,
                ProductPhoto.role == PhotoRole.ORIGINAL,
            )
            .order_by(ProductPhoto.created_at)
        ).all()
        # Seller-approved enhanced photos lead; the untouched originals always follow, so
        # the listing keeps the promise its description makes. A seller who withdrew
        # approval simply gets their originals.
        photos = [*enhanced, *originals]
        intake = (item.constraints_json or {}).get("intake") or {}
        return templates.TemplateResponse(
            request,
            "demo_ebay.html",
            {
                "item": item,
                "pack": pack,
                "photos": photos,
                "enhanced_ids": {photo.id for photo in enhanced},
                "condition_label": condition_label(pack.condition),
                "shipping_label": shipping_label(intake.get("shipping")),
                "deadline": item.deadline_at,
                "clock": request.app.state.clock.now(),
            },
        )
