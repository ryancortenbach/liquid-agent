from __future__ import annotations

import asyncio
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
from fastapi.responses import FileResponse, HTMLResponse
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
from app.inbound.identify import ClaudeIdentifier, Identifier, OpenAIIdentifier
from app.intake.details import IntakeDetails, merge_details
from app.intake.flow import ListingFlow, pack_dict
from app.intake.router import PipelineRouter
from app.ledger import write_decision
from app.listing.draft import polish_with_claude
from app.market import publish_service
from app.market.ebay import (
    EbayError,
    EbayPublisher,
    EbaySandboxClient,
)
from app.market.ebay_oauth import EbayConnectionService, EbayOAuthClient
from app.market.fees import instant_quote_cents
from app.market.publish_service import EbayPublishError
from app.models import (
    ConversationStatus,
    Item,
    ItemStatus,
    LedgerEvent,
    Listing,
    ListingPack,
    ListingStatus,
    PhotoRole,
    PhotoStatus,
    ProductPhoto,
    Seller,
    SellerConversation,
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
from app.photos.reviewer import OpenAIPhotoTruthReviewer, PhotoTruthReviewer
from app.photos.storage import MAX_PHOTO_BYTES, PhotoStorage
from app.pricing.loop import reprice_loop
from app.pricing.repricer import reprice_item
from app.research.factory import build_comps_sources
from app.web.dashboard import router as dashboard_router


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


class DetailsRequest(BaseModel):
    text: str


class PlanListingRequest(BaseModel):
    research: bool = True


class ClockSkipRequest(BaseModel):
    hours: float = Field(gt=0, le=24 * 400)


class EbayListingRequest(BaseModel):
    seller_approved: bool = False
    price_cents: int | None = Field(default=None, gt=0)
    category_id: str | None = None
    description: str | None = None
    aspects: dict[str, list[str]] = Field(default_factory=dict)


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
    ebay_publisher: EbayPublisher | None = None,
    ebay_connection_service: EbayConnectionService | None = None,
    identifier: Identifier | None = None,
    photo_reviewer: PhotoTruthReviewer | None = None,
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
        app.state.photo_reviewer = photo_reviewer
        if (
            app.state.photo_reviewer is None
            and app_settings.openai_api_key
            and app_settings.openai_truth_check
        ):
            app.state.photo_reviewer = OpenAIPhotoTruthReviewer(
                app_settings.openai_api_key,
                model=app_settings.openai_vision_model,
            )
        app.state.message_adapter = message_adapter
        app.state.owns_message_adapter = False
        if app.state.message_adapter is None and app_settings.bb_password:
            app.state.message_adapter = BlueBubblesAdapter(
                app_settings.bb_server_url,
                app_settings.bb_password,
            )
            app.state.owns_message_adapter = True
        app.state.ebay_connections = ebay_connection_service
        app.state.owns_ebay_connections = False
        ebay_client_id = (
            app_settings.ebay_sb_client_id
            if app_settings.ebay_environment == "sandbox"
            else app_settings.ebay_client_id
        )
        ebay_client_secret = (
            app_settings.ebay_sb_client_secret
            if app_settings.ebay_environment == "sandbox"
            else app_settings.ebay_client_secret
        )
        ebay_runame = (
            app_settings.ebay_sb_runame
            if app_settings.ebay_environment == "sandbox"
            else app_settings.ebay_runame
        )
        if app.state.ebay_connections is None and all(
            (ebay_client_id, ebay_client_secret, ebay_runame, app_settings.app_secret)
        ):
            app.state.ebay_connections = EbayConnectionService(
                engine=app.state.engine,
                oauth=EbayOAuthClient(
                    ebay_client_id or "",
                    ebay_client_secret or "",
                    ebay_runame or "",
                    environment=app_settings.ebay_environment,
                ),
                app_secret=app_settings.app_secret or "",
            )
            app.state.owns_ebay_connections = True
        app.state.identifier = identifier
        if app.state.identifier is None:
            if app_settings.identifier_provider == "openai" and app_settings.openai_api_key:
                app.state.identifier = OpenAIIdentifier(
                    app_settings.openai_api_key, model=app_settings.openai_vision_model
                )
            elif app_settings.anthropic_api_key:
                app.state.identifier = ClaudeIdentifier(
                    app_settings.anthropic_api_key, model=app_settings.claude_model
                )
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
                ebay_authorization_url=(
                    app.state.ebay_connections.authorization_url
                    if app.state.ebay_connections is not None
                    else None
                ),
                require_ebay_onboarding=app_settings.require_ebay_onboarding,
                identifier=app.state.identifier,
                reviewer=app.state.photo_reviewer,
            )
        app.state.ebay_publisher = ebay_publisher
        app.state.owns_ebay_publisher = False
        if app.state.ebay_publisher is None and all(
            (
                app_settings.ebay_sb_client_id,
                app_settings.ebay_sb_client_secret,
                app_settings.ebay_sb_refresh_token,
            )
        ):
            app.state.ebay_publisher = EbaySandboxClient(
                app_settings.ebay_sb_client_id or "",
                app_settings.ebay_sb_client_secret or "",
                app_settings.ebay_sb_refresh_token or "",
            )
            app.state.owns_ebay_publisher = True
        app.state.comps_sources = build_comps_sources(app_settings)
        polish = (
            (
                lambda draft: polish_with_claude(
                    draft,
                    api_key=app_settings.anthropic_api_key or "",
                    model=app_settings.claude_model,
                )
            )
            if app_settings.anthropic_api_key
            else None
        )
        app.state.listing_flow = ListingFlow(
            engine=app.state.engine,
            clock=app.state.clock,
            settings=app_settings,
            comps_sources=app.state.comps_sources,
            adapter=app.state.message_adapter,
            ebay_publisher=app.state.ebay_publisher,
            ebay_publisher_for_seller=(
                app.state.ebay_connections.publisher_for
                if app.state.ebay_connections is not None
                else None
            ),
            polish=polish,
        )
        if app.state.seller_router is not None:
            app.state.seller_router = PipelineRouter(
                app.state.seller_router, app.state.listing_flow
            )
        app.state.reprice_stop = asyncio.Event()
        app.state.reprice_task = None
        if app_settings.reprice_loop:
            app.state.reprice_task = asyncio.create_task(
                reprice_loop(
                    engine=app.state.engine,
                    clock=app.state.clock,
                    settings=app_settings,
                    item_locks=app.state.item_locks,
                    ebay_publisher=app.state.ebay_publisher,
                    adapter=app.state.message_adapter,
                    stop=app.state.reprice_stop,
                )
            )
        yield
        app.state.reprice_stop.set()
        if app.state.reprice_task is not None:
            await app.state.reprice_task
        if app.state.owns_message_adapter and app.state.message_adapter is not None:
            await app.state.message_adapter.close()
        if app.state.owns_ebay_publisher and app.state.ebay_publisher is not None:
            await app.state.ebay_publisher.close()
        if app.state.owns_ebay_connections and app.state.ebay_connections is not None:
            await app.state.ebay_connections.close()

    app = FastAPI(title="Liquid", version="0.1.0", lifespan=lifespan)
    app.include_router(dashboard_router)

    @app.get("/health")
    def health(clock: ClockDep) -> dict:
        return {"status": "ok", "mode": app_settings.mode, "sim_at": clock.now()}

    @app.get("/oauth/ebay/callback", response_class=HTMLResponse)
    async def ebay_oauth_callback(
        request: Request,
        state: str | None = None,
        code: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        service: EbayConnectionService | None = request.app.state.ebay_connections
        if service is None:
            raise HTTPException(status_code=503, detail="eBay OAuth is not configured")
        if error:
            if state:
                try:
                    seller_id = service.seller_id_for_state(state)
                except ValueError:
                    seller_id = None
                if seller_id:
                    adapter: BlueBubblesAdapter | None = request.app.state.message_adapter
                    with Session(request.app.state.engine) as session:
                        conversation = session.exec(
                            select(SellerConversation).where(
                                SellerConversation.seller_id == seller_id
                            )
                        ).first()
                    if adapter is not None and conversation is not None:
                        await adapter.send_text(
                            conversation.chat_guid,
                            "eBay was not connected. Reply RETRY for a fresh link.",
                            f"ebay-declined:{seller_id}:{state[-16:]}",
                        )
            return HTMLResponse(
                "<h1>eBay was not connected</h1>"
                "<p>Return to Messages and reply RETRY for a fresh link.</p>",
                status_code=400,
            )
        if not state or not code:
            raise HTTPException(status_code=400, detail="eBay callback is missing state or code")
        try:
            seller_id = service.seller_id_for_state(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            connection = await service.complete(state, code)
        except (ValueError, EbayError):
            adapter: BlueBubblesAdapter | None = request.app.state.message_adapter
            with Session(request.app.state.engine) as session:
                conversation = session.exec(
                    select(SellerConversation).where(SellerConversation.seller_id == seller_id)
                ).first()
            if adapter is not None and conversation is not None:
                await adapter.send_text(
                    conversation.chat_guid,
                    "eBay connection failed. Reply RETRY for a fresh link.",
                    f"ebay-failed:{seller_id}:{state[-16:]}",
                )
            return HTMLResponse(
                "<h1>eBay connection failed</h1>"
                "<p>Return to Messages and reply RETRY for a fresh link.</p>",
                status_code=400,
            )
        adapter: BlueBubblesAdapter | None = request.app.state.message_adapter
        chat_guid: str | None = None
        with Session(request.app.state.engine) as session:
            conversation = session.exec(
                select(SellerConversation).where(
                    SellerConversation.seller_id == connection.seller_id
                )
            ).first()
            if conversation is not None:
                chat_guid = conversation.chat_guid
                conversation.status = ConversationStatus.READY
                conversation.updated_at = utc_now()
                session.add(conversation)
                session.commit()
        if adapter is not None and chat_guid is not None:
            await adapter.send_text(
                chat_guid,
                "eBay connected. Setup is complete. Send one or more product photos to start.",
                f"ebay-connected:{connection.id}:{connection.updated_at.isoformat()}",
            )
        return HTMLResponse(
            "<h1>eBay connected</h1><p>You can close this page and return to Messages.</p>"
        )

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

    @app.post("/api/items/{item_id}/publish/ebay")
    async def publish_item_to_ebay(
        item_id: str,
        body: EbayListingRequest,
        request: Request,
        engine: EngineDep,
        clock: ClockDep,
    ) -> dict:
        try:
            result = await publish_service.publish_item_to_ebay(
                engine=engine,
                settings=app_settings,
                publisher=request.app.state.ebay_publisher,
                publisher_for_seller=(
                    request.app.state.ebay_connections.publisher_for
                    if request.app.state.ebay_connections is not None
                    else None
                ),
                clock=clock,
                item_id=item_id,
                seller_approved=body.seller_approved,
                price_cents=body.price_cents,
                category_id=body.category_id,
                description=body.description,
                aspects=body.aspects,
            )
        except EbayPublishError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return result.as_dict()

    @app.post("/api/identify")
    async def identify_photo(
        request: Request,
        upload: Annotated[UploadFile, File()],
        caption: Annotated[str, Form()] = "",
        item_id: Annotated[str | None, Form()] = None,
        engine: EngineDep = None,  # type: ignore[assignment]
    ) -> dict:
        """Identify a product photo (and optionally apply the result to an item)."""
        identifier: Identifier | None = request.app.state.identifier
        if identifier is None:
            raise HTTPException(status_code=503, detail="no identifier is configured")
        content = await upload.read(MAX_PHOTO_BYTES + 1)
        if not content:
            raise HTTPException(status_code=422, detail="photo is empty")
        identity = await identifier.identify(content, upload.content_type or "image/jpeg", caption)
        payload = identity.model_dump() | {"question": identity.question()}
        if item_id:
            with Session(engine) as session:
                item = session.get(Item, item_id)
                if item is None:
                    raise HTTPException(status_code=404, detail="item not found")
                SellerMessageRouter._apply_identity(item, identity)
                item.constraints_json = {**item.constraints_json, "identity_confirmed": False}
                session.add(item)
                write_decision(
                    session,
                    item_id=item.id,
                    sim_at=request.app.state.clock.now(),
                    wall_at=request.app.state.clock.wall(),
                    kind="system",
                    action="identify",
                    inputs={"title": identity.title, "confidence": identity.confidence},
                    reason="identified from the uploaded photo (API)",
                    price_before=None,
                    price_after=None,
                )
                session.commit()
                payload["item_id"] = item.id
                payload["title_applied"] = item.title
        return payload

    @app.post("/api/items/{item_id}/details")
    def add_details(item_id: str, body: DetailsRequest, engine: EngineDep) -> dict:
        with Session(engine) as session:
            item = session.get(Item, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="item not found")
            asked = list(item.constraints_json.get("intake_asked") or [])
            details = merge_details(
                IntakeDetails.from_dict(item.constraints_json.get("intake")),
                body.text,
                answered_set="api",
            )
            item.constraints_json = {
                **item.constraints_json,
                "intake": details.as_dict(),
                "intake_asked": asked,
            }
            session.add(item)
            session.commit()
            return details.as_dict()

    @app.post("/api/items/{item_id}/plan-listing")
    async def plan_listing(item_id: str, body: PlanListingRequest, request: Request) -> dict:
        flow: ListingFlow = request.app.state.listing_flow
        try:
            result = await flow.plan(item_id, research=body.research)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result.as_dict()

    @app.post("/api/items/{item_id}/go")
    async def go(item_id: str, request: Request) -> dict:
        flow: ListingFlow = request.app.state.listing_flow
        try:
            return await flow.publish(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/items/{item_id}/reprice")
    async def reprice(item_id: str, request: Request, engine: EngineDep, clock: ClockDep) -> dict:
        try:
            outcome = await reprice_item(
                engine=engine,
                clock=clock,
                settings=app_settings,
                item_id=item_id,
                ebay_publisher=request.app.state.ebay_publisher,
                adapter=request.app.state.message_adapter,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return outcome.as_dict()

    @app.post("/api/clock/skip")
    def clock_skip(body: ClockSkipRequest, clock: ClockDep) -> dict:
        delta = timedelta(hours=body.hours)
        if isinstance(clock, SimClock):
            now = clock.advance(delta)
        elif isinstance(clock, DemoClock):
            now = clock.skip(delta)
        else:
            raise HTTPException(status_code=409, detail="the real clock cannot be skipped")
        return {"sim_at": now}

    @app.post("/api/clock/{action}")
    def clock_control(action: str, clock: ClockDep) -> dict:
        if not isinstance(clock, DemoClock):
            raise HTTPException(status_code=409, detail="only the demo clock can be paused")
        if action == "pause":
            return {"sim_at": clock.pause(), "paused": True}
        if action == "resume":
            return {"sim_at": clock.resume(), "paused": False}
        raise HTTPException(status_code=404, detail="unknown clock action")

    @app.get("/api/items/{item_id}/packs")
    def list_packs(item_id: str, engine: EngineDep) -> list[dict]:
        with Session(engine) as session:
            if session.get(Item, item_id) is None:
                raise HTTPException(status_code=404, detail="item not found")
            packs = session.exec(select(ListingPack).where(ListingPack.item_id == item_id)).all()
            return [pack_dict(pack) for pack in packs]

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
                reviewer=request.app.state.photo_reviewer,
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
