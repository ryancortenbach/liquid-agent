from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, Index, text
from sqlmodel import Field, SQLModel

from app.clock import utc_now
from app.ids import new_id


class ConditionGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class ItemStatus(StrEnum):
    DRAFT = "draft"
    IDENTIFIED = "identified"
    PRICED = "priced"
    LIVE = "live"
    SALE_PENDING = "sale_pending"
    ESCALATED = "escalated"
    SOLD = "sold"
    LABELED = "labeled"
    SCHEDULED = "scheduled"
    DONE = "done"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ListingStatus(StrEnum):
    DRAFT = "draft"
    LIVE = "live"
    PAUSED = "paused"
    ENDED = "ended"


class OfferStatus(StrEnum):
    OPEN = "open"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class SaleClaimStatus(StrEnum):
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    RELEASED = "released"


class PhotoRole(StrEnum):
    ORIGINAL = "original"
    ENHANCED = "enhanced"


class PhotoStatus(StrEnum):
    ORIGINAL = "original"
    PROCESSING = "processing"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ConversationStatus(StrEnum):
    AWAITING_EBAY = "awaiting_ebay"
    READY = "ready"
    PROCESSING_PHOTO = "processing_photo"
    AWAITING_IDENTITY = "awaiting_identity"
    AWAITING_PHOTO_REVIEW = "awaiting_photo_review"
    AWAITING_DETAILS = "awaiting_details"
    RESEARCHING = "researching"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PUBLISHING = "publishing"
    LISTED = "listed"


class Seller(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    handle: str = Field(index=True, unique=True)
    name: str | None = None
    tz: str = "America/Los_Angeles"
    from_address_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )


class EbayConnection(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    seller_id: str = Field(foreign_key="seller.id", index=True, unique=True)
    environment: str
    encrypted_refresh_token: str
    scopes_json: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    connected_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SellerConversation(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    seller_id: str = Field(foreign_key="seller.id", index=True, unique=True)
    handle: str = Field(index=True, unique=True)
    chat_guid: str
    active_item_id: str | None = Field(default=None, foreign_key="item.id", index=True)
    pending_photo_id: str | None = Field(
        default=None,
        foreign_key="productphoto.id",
        index=True,
    )
    status: ConversationStatus = ConversationStatus.READY
    updated_at: datetime = Field(default_factory=utc_now)


class Item(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    seller_id: str = Field(foreign_key="seller.id", index=True)
    title: str
    brand: str | None = None
    model: str | None = None
    category: str = "other"
    condition: ConditionGrade = ConditionGrade.B
    confidence: float = Field(default=0.0, ge=0, le=1)
    photo_paths: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    deadline_at: datetime
    original_horizon_hours: float = Field(gt=0)
    floor_cents: int = Field(ge=0)
    floor_source: str = "derived"
    constraints_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    market_value_cents: int = Field(gt=0)
    sigma_cents: int = Field(gt=0)
    comps_n: int = Field(default=0, ge=0)
    instant_quote_cents: int = Field(default=0, ge=0)
    instant_preauthorized: bool = False
    status: ItemStatus = ItemStatus.DRAFT
    escalated_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Listing(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    channel: str
    external_id: str | None = None
    price_cents: int = Field(ge=0)
    status: ListingStatus = ListingStatus.DRAFT
    published_at: datetime | None = None
    last_reprice_at: datetime | None = None


class ProductPhoto(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    source_photo_id: str | None = Field(default=None, foreign_key="productphoto.id", index=True)
    role: PhotoRole
    status: PhotoStatus
    file_path: str
    mime_type: str
    sha256: str
    preset: str | None = None
    prompt: str | None = None
    model: str | None = None
    disclosure: str | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_at: datetime | None = None


class Buyer(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    handle: str = Field(index=True)
    channel: str = "facebook"
    name: str | None = None
    close_reliability: float = Field(default=0.85, ge=0, le=1)
    failed_close_count: int = Field(default=0, ge=0)


class Offer(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    buyer_id: str = Field(foreign_key="buyer.id", index=True)
    amount_cents: int = Field(gt=0)
    direction: str = "in"
    status: OfferStatus = OfferStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None


class SaleClaim(SQLModel, table=True):
    __table_args__ = (
        Index(
            "uq_sale_claim_item_active",
            "item_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    offer_id: str = Field(foreign_key="offer.id", index=True)
    channel: str
    external_reference: str | None = None
    amount_cents: int = Field(gt=0)
    status: SaleClaimStatus = SaleClaimStatus.ACTIVE
    claimed_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolution_source: str | None = None


class Shipment(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True, unique=True)
    shippo_transaction_id: str
    label_url: str
    tracking: str
    carrier: str
    rate_cents: int = Field(ge=0)


class CalendarEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True, unique=True)
    gcal_event_id: str
    starts_at: datetime


class LedgerEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    sim_at: datetime
    wall_at: datetime = Field(default_factory=utc_now)
    kind: str = "tick"
    action: str
    inputs_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    reason: str
    price_before: int | None = None
    price_after: int | None = None


class Outbox(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    idempotency_key: str = Field(index=True, unique=True)
    attempts: int = Field(default=0, ge=0)
    next_at: datetime = Field(default_factory=utc_now)
    done_at: datetime | None = None
    error: str | None = None


class WebhookReceipt(SQLModel, table=True):
    provider: str = Field(primary_key=True)
    event_id: str = Field(primary_key=True)
    received_at: datetime = Field(default_factory=utc_now)


class DemandObs(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    channel: str
    kind: str
    sim_at: datetime
    value: float = Field(default=1.0, ge=0)


class ListingPackStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    HANDOFF_READY = "handoff_ready"
    FAILED = "failed"


class ResearchResult(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    query: str
    sold_n: int = Field(default=0, ge=0)
    active_n: int = Field(default=0, ge=0)
    sold_median_cents: int | None = None
    active_median_cents: int | None = None
    market_value_cents: int = Field(gt=0)
    sigma_cents: int = Field(gt=0)
    basis: str = "active"
    sources_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    specifics_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utc_now)


class ListingPack(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    channel: str
    title: str
    description: str
    price_cents: int = Field(gt=0)
    condition: str = "USED_GOOD"
    specifics_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    photo_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    schedule_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    sources_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    status: ListingPackStatus = ListingPackStatus.DRAFT
    external_id: str | None = None
    external_offer_id: str | None = None
    external_url: str | None = None
    handoff_path: str | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
