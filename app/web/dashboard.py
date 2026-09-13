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
