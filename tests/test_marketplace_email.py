from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlmodel import Session, select

from app.db import create_db_and_tables, make_engine
from app.mail.gmail import GmailConnectionService, GmailOAuthClient, GmailStateSigner
from app.mail.marketplace import MarketplaceEmailProcessor, parse_marketplace_email
from app.models import (
    EmailConnection,
    Item,
    ItemStatus,
    Listing,
    ListingStatus,
    MarketplaceEmailEvent,
    Offer,
    Outbox,
    SaleClaim,
    SaleClaimStatus,
    Seller,
)

NOW = datetime(2026, 9, 13, 16, tzinfo=UTC)


def setup_listed_item() -> tuple:
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    with Session(engine) as session:
        seller = Seller(id="seller-1", handle="+14155550123")
        session.add(seller)
        session.flush()
        item = Item(
            id="item-1",
            seller_id=seller.id,
            title="Sony WH-1000XM5 headphones",
            deadline_at=NOW + timedelta(days=3),
            original_horizon_hours=72,
            floor_cents=17_000,
            market_value_cents=22_000,
            sigma_cents=2_000,
            status=ItemStatus.LIVE,
        )
        session.add(item)
        session.flush()
        session.add(
            Listing(
                item_id=item.id,
                channel="ebay",
                external_id="123456789012",
                price_cents=21_000,
                status=ListingStatus.LIVE,
            )
        )
        session.commit()
    return engine


def authenticated_email(kind: str):
    subject = (
        "You received an offer for Sony WH-1000XM5 headphones"
        if kind == "offer"
        else "You made the sale: Sony WH-1000XM5 headphones"
    )
    return parse_marketplace_email(
        sender="eBay <notify@reply.ebay.com>",
        subject=subject,
        body="Item number: 123456789012. Total: $198.00",
        authentication_results="mx.google.com; dkim=pass header.i=@ebay.com",
    )


def test_parser_rejects_unknown_senders_and_requires_mail_authentication() -> None:
    assert (
        parse_marketplace_email(
            sender="scammer@example.com",
            subject="Your item sold",
            body="Sony WH-1000XM5 sold for $1.00",
        )
        is None
    )
    parsed = parse_marketplace_email(
        sender="notify@reply.ebay.com",
        subject="You received an offer for Sony WH-1000XM5 headphones",
        body="$198.00",
    )
    assert parsed is not None
    assert parsed.kind == "offer"
    assert parsed.source_authenticated is False


def test_authenticated_offer_is_recorded_once() -> None:
    engine = setup_listed_item()
    parsed = authenticated_email("offer")
    assert parsed is not None
    processor = MarketplaceEmailProcessor(engine)

    result = processor.process(
        seller_id="seller-1",
        provider="gmail:seller-1",
        message_id="gmail-offer-1",
        parsed=parsed,
        received_at=NOW,
        wall_at=NOW,
    )
    duplicate = processor.process(
        seller_id="seller-1",
        provider="gmail:seller-1",
        message_id="gmail-offer-1",
        parsed=parsed,
        received_at=NOW,
        wall_at=NOW,
    )

    assert result.status == "recorded" and result.item_id == "item-1"
    assert duplicate.duplicate is True and duplicate.notification is None
    with Session(engine) as session:
        assert len(session.exec(select(Offer)).all()) == 1
        event = session.get(MarketplaceEmailEvent, ("gmail:seller-1", "gmail-offer-1"))
        assert event is not None and event.source_authenticated is True


def test_authenticated_sold_email_ends_all_listings() -> None:
    engine = setup_listed_item()
    with Session(engine) as session:
        session.add(
            Listing(
                item_id="item-1",
                channel="facebook",
                price_cents=21_000,
                status=ListingStatus.LIVE,
            )
        )
        session.commit()
    parsed = authenticated_email("sold")
    assert parsed is not None

    result = MarketplaceEmailProcessor(engine).process(
        seller_id="seller-1",
        provider="gmail:seller-1",
        message_id="gmail-sale-1",
        parsed=parsed,
        received_at=NOW,
        wall_at=NOW,
    )

    assert result.status == "applied"
    with Session(engine) as session:
        assert session.get(Item, "item-1").status == ItemStatus.SOLD
        assert {row.status for row in session.exec(select(Listing)).all()} == {ListingStatus.ENDED}
        claim = session.exec(select(SaleClaim)).one()
        assert claim.status == SaleClaimStatus.CONFIRMED
        assert session.exec(select(Outbox)).one().kind == "end_other_listings"


@pytest.mark.asyncio
async def test_gmail_oauth_encrypts_refresh_token_and_can_send_alert(tmp_path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/token":
            form = request.content.decode()
            if "authorization_code" in form:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "initial-access",
                        "refresh_token": "refresh-secret",
                        "scope": " ".join(
                            (
                                "https://www.googleapis.com/auth/gmail.readonly",
                                "https://www.googleapis.com/auth/gmail.send",
                            )
                        ),
                    },
                )
            return httpx.Response(200, json={"access_token": "refreshed-access"})
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "seller@gmail.com"})
        if request.url.path.endswith("/messages/send"):
            return httpx.Response(200, json={"id": "sent-1"})
        return httpx.Response(404)

    client_json = tmp_path / "gmail.json"
    client_json.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "google-client",
                    "client_secret": "google-secret",
                    "auth_uri": "https://accounts.example.com/auth",
                    "token_uri": "https://accounts.example.com/token",
                }
            }
        )
    )
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    with Session(engine) as session:
        session.add(Seller(id="seller-1", handle="+14155550123"))
        session.commit()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    oauth = GmailOAuthClient(
        str(client_json),
        "https://liquid.example.com/oauth/google/gmail/callback",
        client=http,
    )
    service = GmailConnectionService(
        engine=engine,
        oauth=oauth,
        app_secret="s" * 32,
    )
    authorization_url = service.authorization_url("seller-1")
    query = parse_qs(urlparse(authorization_url).query)

    assert query["access_type"] == ["offline"]
    assert "gmail.readonly" in query["scope"][0]
    connection = await service.complete(query["state"][0], "authorization-code")
    assert connection.email_address == "seller@gmail.com"
    assert await service.send_alert("seller-1", "Listing is live", "https://example.com/item")

    with Session(engine) as session:
        stored = session.exec(select(EmailConnection)).one()
        assert stored.encrypted_refresh_token != "refresh-secret"
        assert service.cipher.decrypt(stored.encrypted_refresh_token) == "refresh-secret"
    assert any(request.url.path.endswith("/messages/send") for request in requests)
    await service.close()
    await http.aclose()


def test_gmail_state_expires() -> None:
    signer = GmailStateSigner("s" * 32)
    state = signer.dumps("seller-1", now=1_000)
    assert signer.loads(state, now=1_599) == "seller-1"
    with pytest.raises(ValueError, match="expired"):
        signer.loads(state, now=1_601)
