from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.channels.seller_router import SellerMessageRouter
from app.clock import Clock, DemoClock, RealClock, SimClock, utc_now
from app.config import Mode, Settings, get_settings
from app.db import ItemLocks, create_db_and_tables, make_engine
from app.engine.demand import optimal_price
from app.engine.executor import apply_action
from app.engine.frontier import compute_frontier
from app.engine.load_state import load_state
from app.engine.policy import decide
from app.engine.state import ItemState, default_channels
from app.ledger import write_decision
from app.market.fees import instant_quote_cents
from app.models import (
    Item,
    ItemStatus,
    LedgerEvent,
    Listing,
    ListingStatus,
    PhotoRole,
    PhotoStatus,
    ProductPhoto,
    Seller,
    WebhookReceipt,
)
from app.photos.editor import (
    OpenAIProductPhotoEditor,
    PhotoPreset,
    ProductPhotoEditor,
)
from app.photos.pipeline import (
    PhotoEditError,
    PhotoInputError,
    PhotoItemNotFound,
    enhance_product_photo,
)
from app.photos.storage import MAX_PHOTO_BYTES, PhotoStorage


class PlanRequest(BaseModel):
    market_value_cents: int = Field(gt=0)
    sigma_cents: int = Field(gt=0)
    floor_cents: int = Field(ge=0)
    deadline_hours: float = Field(gt=0)
    category: str = "electronics"
    instant_ok: bool = True


class CreateItemRequest(PlanRequest):
    seller_handle: str
    title: str
    brand: str | None = None
    model: str | None = None
    opening_price_cents: int | None = Field(default=None, gt=0)


class PhotoReviewRequest(BaseModel):
    approved: bool


def build_clock(settings: Settings) -> Clock:
    if settings.mode == Mode.REAL:
        return RealClock()
    if settings.mode == Mode.SIM:
        return SimClock(utc_now())
    return DemoClock(start=utc_now(), speed=settings.demo_clock_speed)


def preview_state(request: PlanRequest, now) -> ItemState:
    return ItemState(
        item_id="preview",
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=request.deadline_hours),
        original_horizon_hours=request.deadline_hours,
        floor_cents=request.floor_cents,
        market_value_cents=request.market_value_cents,
        sigma_cents=request.sigma_cents,
        instant_quote_cents=instant_quote_cents(request.market_value_cents, request.category),
        instant_ok=request.instant_ok,
        channels=default_channels(),
    )


def plan_payload(state: ItemState, hours: float) -> dict:
    optimal = optimal_price(state, hours)
    frontier = compute_frontier(state)
    return {
        "opening_price_cents": optimal.price_cents,
        "expected_value_cents": round(optimal.expected_value_cents),
        "sale_probability": round(optimal.sale_probability, 4),
        "instant_cents": frontier.instant_cents,
        "frontier": [
            {
                "hours": point.hours,
                "price_cents": point.price_cents,
                "probability": round(point.probability, 4),
            }
            for point in frontier.points
        ],
    }


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_item_locks(request: Request) -> ItemLocks:
    return request.app.state.item_locks


EngineDep = Annotated[Engine, Depends(get_engine)]
ClockDep = Annotated[Clock, Depends(get_clock)]
ItemLocksDep = Annotated[ItemLocks, Depends(get_item_locks)]


def create_app(
    settings: Settings | None = None,
    *,
    photo_editor: ProductPhotoEditor | None = None,
    message_adapter: BlueBubblesAdapter | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = make_engine(app_settings.database_url)
        create_db_and_tables(app.state.engine)
        app.state.clock = build_clock(app_settings)
        app.state.item_locks = ItemLocks()
        app.state.photo_storage = PhotoStorage(app_settings.photo_storage_dir)
        app.state.photo_editor = photo_editor
        if app.state.photo_editor is None and app_settings.openai_api_key:
            app.state.photo_editor = OpenAIProductPhotoEditor(
                app_settings.openai_api_key,
                model=app_settings.openai_image_model,
                quality=app_settings.openai_image_quality,
                size=app_settings.openai_image_size,
            )
        app.state.message_adapter = message_adapter
        app.state.owns_message_adapter = False
        if app.state.message_adapter is None and app_settings.bb_password:
            app.state.message_adapter = BlueBubblesAdapter(
                app_settings.bb_server_url,
                app_settings.bb_password,
            )
            app.state.owns_message_adapter = True
        app.state.seller_router = None
        if app.state.message_adapter is not None and app_settings.seller_handle:
            app.state.seller_router = SellerMessageRouter(
                engine=app.state.engine,
                clock=app.state.clock,
                adapter=app.state.message_adapter,
                editor=app.state.photo_editor,
                storage=app.state.photo_storage,
                seller_handle=app_settings.seller_handle,
                timezone=app_settings.tz,
            )
        yield
        if app.state.owns_message_adapter and app.state.message_adapter is not None:
            await app.state.message_adapter.close()

    app = FastAPI(title="Liquid", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health(clock: ClockDep) -> dict:
        return {"status": "ok", "mode": app_settings.mode, "sim_at": clock.now()}

    async def process_bluebubbles_message(message) -> None:
        router: SellerMessageRouter = app.state.seller_router
        try:
            await router.route(message)
        except Exception:
            with Session(app.state.engine) as session:
                receipt = session.get(WebhookReceipt, ("bluebubbles", message.guid))
                if receipt is not None:
                    session.delete(receipt)
                    session.commit()

    @app.post("/webhooks/bluebubbles", status_code=202)
    async def bluebubbles_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        engine: EngineDep,
        secret: str | None = None,
    ) -> dict:
        expected_secret = app_settings.bb_webhook_secret
        if not expected_secret:
            raise HTTPException(status_code=503, detail="BlueBubbles webhook is not configured")
        if not secret or not secrets.compare_digest(secret, expected_secret):
            raise HTTPException(status_code=401, detail="invalid webhook secret")
        adapter: BlueBubblesAdapter | None = request.app.state.message_adapter
        router: SellerMessageRouter | None = request.app.state.seller_router
        if adapter is None or router is None:
            raise HTTPException(status_code=503, detail="seller iMessage routing is not configured")
        try:
            payload = await request.json()
            message = adapter.parse_inbound(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="invalid BlueBubbles payload") from exc
        if message is None:
            return {"status": "ignored"}
        if not router.accepts(message):
            return {"status": "ignored", "reason": "sender_not_allowed"}

        with Session(engine) as session:
            existing = session.get(WebhookReceipt, ("bluebubbles", message.guid))
            if existing is not None:
                return {"status": "duplicate"}
            session.add(WebhookReceipt(provider="bluebubbles", event_id=message.guid))
            session.commit()
        background_tasks.add_task(process_bluebubbles_message, message)
        return {"status": "queued"}

    @app.post("/api/plan")
    def plan(body: PlanRequest, clock: ClockDep) -> dict:
        now = clock.now()
        state = preview_state(body, now)
        return plan_payload(state, body.deadline_hours)

    @app.post("/api/items", status_code=201)
    def create_item(
        body: CreateItemRequest,
        engine: EngineDep,
        clock: ClockDep,
    ) -> dict:
        now = clock.now()
        preview = preview_state(body, now)
        opening = (
            body.opening_price_cents or optimal_price(preview, body.deadline_hours).price_cents
        )
        if opening < body.floor_cents:
            raise HTTPException(status_code=422, detail="opening price cannot be below floor")

        with Session(engine) as session:
            seller = session.exec(select(Seller).where(Seller.handle == body.seller_handle)).first()
            if seller is None:
                seller = Seller(handle=body.seller_handle, tz=app_settings.tz)
                session.add(seller)
                session.flush()
            item = Item(
                seller_id=seller.id,
                title=body.title,
                brand=body.brand,
                model=body.model,
                category=body.category,
                confidence=1,
                deadline_at=now + timedelta(hours=body.deadline_hours),
                original_horizon_hours=body.deadline_hours,
                floor_cents=body.floor_cents,
                floor_source="seller",
                constraints_json={"instant_ok": body.instant_ok},
                market_value_cents=body.market_value_cents,
                sigma_cents=body.sigma_cents,
                instant_quote_cents=preview.instant_quote_cents,
                status=ItemStatus.LIVE,
                created_at=now,
            )
            session.add(item)
            session.flush()
            listing = Listing(
                item_id=item.id,
                channel="ebay",
                price_cents=opening,
                status=ListingStatus.LIVE,
                published_at=now,
            )
            session.add(listing)
            write_decision(
                session,
                item_id=item.id,
                sim_at=now,
                wall_at=clock.wall(),
                kind="system",
                action="list",
                inputs=plan_payload(preview, body.deadline_hours),
                reason="created item from validated market inputs",
                price_before=None,
                price_after=opening,
            )
            session.commit()
            return {"item_id": item.id, **plan_payload(preview, body.deadline_hours)}

    @app.post("/api/items/{item_id}/tick")
    async def tick_item(
        item_id: str,
        engine: EngineDep,
        clock: ClockDep,
        item_locks: ItemLocksDep,
    ) -> dict:
        async with item_locks.for_item(item_id):
            with Session(engine) as session:
                try:
                    state = load_state(session, item_id)
                except LookupError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                now = clock.now()
                action = decide(state, now)
                result = apply_action(
                    session,
                    state,
                    action,
                    now=now,
                    wall_at=clock.wall(),
                )
                return {
                    "action": action.kind,
                    "reason": action.reason,
                    "applied": result.applied,
                    "violation": result.violation,
                    "inputs": action.inputs,
                }

    @app.get("/api/items/{item_id}/ledger")
    def ledger(item_id: str, engine: EngineDep) -> list[LedgerEvent]:
        with Session(engine) as session:
            if session.get(Item, item_id) is None:
                raise HTTPException(status_code=404, detail="item not found")
            return list(
                session.exec(
                    select(LedgerEvent)
                    .where(LedgerEvent.item_id == item_id)
                    .order_by(LedgerEvent.sim_at)
                ).all()
            )

    @app.post("/api/items/{item_id}/photos/enhance", status_code=201)
    async def enhance_photo(
        item_id: str,
        request: Request,
        engine: EngineDep,
        upload: Annotated[UploadFile, File()],
        preset: Annotated[PhotoPreset, Form()] = PhotoPreset.STUDIO,
    ) -> dict:
        editor: ProductPhotoEditor | None = request.app.state.photo_editor
        if editor is None:
            raise HTTPException(
                status_code=503,
                detail="OpenAI image editing is not configured",
            )

        content = await upload.read(MAX_PHOTO_BYTES + 1)
        storage: PhotoStorage = request.app.state.photo_storage
        try:
            result = await enhance_product_photo(
                engine=engine,
                item_id=item_id,
                content=content,
                mime_type=upload.content_type or "",
                preset=preset,
                editor=editor,
                storage=storage,
            )
        except PhotoItemNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PhotoInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PhotoEditError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "original_photo_id": result.original.id,
            "enhanced_photo_id": result.enhanced.id,
            "status": PhotoStatus.REVIEW,
            "original_url": f"/api/photos/{result.original.id}/file",
            "enhanced_url": f"/api/photos/{result.enhanced.id}/file",
            "requires_seller_approval": True,
            "disclosure": "AI-enhanced lighting and background. Original image retained.",
        }

    @app.post("/api/items/{item_id}/photos/{photo_id}/review")
    def review_photo(
        item_id: str,
        photo_id: str,
        body: PhotoReviewRequest,
        engine: EngineDep,
        clock: ClockDep,
    ) -> dict:
        with Session(engine) as session:
            item = session.get(Item, item_id)
            photo = session.get(ProductPhoto, photo_id)
            if item is None or photo is None or photo.item_id != item_id:
                raise HTTPException(status_code=404, detail="photo not found")
            if photo.role != PhotoRole.ENHANCED or photo.status != PhotoStatus.REVIEW:
                raise HTTPException(status_code=409, detail="photo is not awaiting review")

            photo.status = PhotoStatus.APPROVED if body.approved else PhotoStatus.REJECTED
            photo.reviewed_at = clock.now()
            if body.approved and photo.file_path not in item.photo_paths:
                item.photo_paths = [*item.photo_paths, photo.file_path]
                session.add(item)
            session.add(photo)
            write_decision(
                session,
                item_id=item.id,
                sim_at=clock.now(),
                wall_at=clock.wall(),
                kind="seller",
                action="approve_photo" if body.approved else "reject_photo",
                inputs={"photo_id": photo.id, "preset": photo.preset},
                reason="seller reviewed the AI-enhanced image",
                price_before=None,
                price_after=None,
            )
            session.commit()
            return {"photo_id": photo.id, "status": photo.status}

    @app.get("/api/items/{item_id}/photos")
    def list_photos(item_id: str, engine: EngineDep) -> list[ProductPhoto]:
        with Session(engine) as session:
            if session.get(Item, item_id) is None:
                raise HTTPException(status_code=404, detail="item not found")
            return list(
                session.exec(
                    select(ProductPhoto)
                    .where(ProductPhoto.item_id == item_id)
                    .order_by(ProductPhoto.created_at)
                ).all()
            )

    @app.get("/api/photos/{photo_id}/file")
    def get_photo_file(photo_id: str, request: Request, engine: EngineDep) -> FileResponse:
        with Session(engine) as session:
            photo = session.get(ProductPhoto, photo_id)
            if photo is None:
                raise HTTPException(status_code=404, detail="photo not found")
            if photo.status in {PhotoStatus.PROCESSING, PhotoStatus.FAILED}:
                raise HTTPException(status_code=409, detail="photo file is not available")
            storage: PhotoStorage = request.app.state.photo_storage
            try:
                path = storage.resolve(photo.file_path)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="photo not found") from exc
            if not path.exists():
                raise HTTPException(status_code=404, detail="photo file not found")
            return FileResponse(path, media_type=photo.mime_type)

    return app


app = create_app()
