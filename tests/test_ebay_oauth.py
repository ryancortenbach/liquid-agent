from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlmodel import Session, select

from app.db import create_db_and_tables, make_engine
from app.market.ebay_oauth import EbayConnectionService, EbayOAuthClient, EbayStateSigner
from app.models import EbayConnection, Seller


def test_ebay_state_is_signed_and_expires() -> None:
    signer = EbayStateSigner("s" * 32, max_age_seconds=600)
    state = signer.dumps("seller-1", now=1_000)

    assert signer.loads(state, now=1_599) == "seller-1"
    with pytest.raises(ValueError, match="expired"):
        signer.loads(state, now=1_601)
    with pytest.raises(ValueError, match="invalid"):
        signer.loads(f"{state}x", now=1_100)


@pytest.mark.asyncio
async def test_oauth_exchange_encrypts_refresh_token_and_builds_seller_publisher() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "short-lived-access",
                "refresh_token": "long-lived-refresh",
                "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory",
            },
        )

    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    with Session(engine) as session:
        session.add(Seller(id="seller-1", handle="+14155550123"))
        session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    oauth = EbayOAuthClient(
        "client-id",
        "client-secret",
        "test-runame",
        environment="sandbox",
        client=http,
    )
    service = EbayConnectionService(engine=engine, oauth=oauth, app_secret="s" * 32)
    authorization_url = service.authorization_url("seller-1")
    query = parse_qs(urlparse(authorization_url).query)

    assert authorization_url.startswith("https://auth.sandbox.ebay.com/oauth2/authorize?")
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["test-runame"]

    await service.complete(query["state"][0], "authorization-code")

    with Session(engine) as session:
        connection = session.exec(
            select(EbayConnection).where(EbayConnection.seller_id == "seller-1")
        ).one()
        assert connection.encrypted_refresh_token != "long-lived-refresh"
        assert service.cipher.decrypt(connection.encrypted_refresh_token) == "long-lived-refresh"
    publisher = service.publisher_for("seller-1")
    assert publisher is not None
    assert publisher.api_base_url == "https://api.sandbox.ebay.com"
    assert requests[0].url.path == "/identity/v1/oauth2/token"

    await service.close()
    await http.aclose()
