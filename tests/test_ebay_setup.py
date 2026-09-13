from __future__ import annotations

import json

import httpx
import pytest

from app.market.ebay_setup import SELLING_POLICY_PROGRAM, EbayAccountClient


@pytest.mark.asyncio
async def test_ensure_seller_setup_creates_only_the_missing_pieces() -> None:
    calls: list[tuple[str, str]] = []
    state = {"opted_in": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 7200})
        if path == "/sell/account/v1/program/get_opted_in_programs":
            programs = [{"programType": SELLING_POLICY_PROGRAM}] if state["opted_in"] else []
            return httpx.Response(200, json={"programs": programs})
        if path == "/sell/account/v1/program/opt_in":
            state["opted_in"] = True
            return httpx.Response(200, json={})
        if path == "/sell/account/v1/payment_policy/get_by_policy_name":
            assert request.url.params["name"] == "Liquid payment policy"
            return httpx.Response(200, json={"paymentPolicyId": "pay-1"})
        if path.endswith("/get_by_policy_name"):
            return httpx.Response(
                404, json={"errors": [{"errorId": 20404, "message": "Policy not found"}]}
            )
        if path == "/sell/account/v1/return_policy":
            body = json.loads(request.read())
            assert body["returnsAccepted"] is True and body["marketplaceId"] == "EBAY_US"
            return httpx.Response(201, json={"returnPolicyId": "ret-1"})
        if path == "/sell/account/v1/fulfillment_policy":
            body = json.loads(request.read())
            service = body["shippingOptions"][0]["shippingServices"][0]
            assert service["shippingServiceCode"] == "USPSPriority" and service["freeShipping"]
            return httpx.Response(201, json={"fulfillmentPolicyId": "ful-1"})
        if path == "/sell/inventory/v1/location/liquid-home" and request.method == "GET":
            return httpx.Response(
                404, json={"errors": [{"errorId": 25804, "message": "Location not found"}]}
            )
        if path == "/sell/inventory/v1/location/liquid-home" and request.method == "POST":
            body = json.loads(request.read())
            assert body["location"]["address"]["postalCode"] == "94105"
            assert body["locationTypes"] == ["WAREHOUSE"]
            return httpx.Response(204)
        return httpx.Response(500, json={"errors": [{"message": f"unexpected {path}"}]})

    client = EbayAccountClient(
        "id", "secret", "refresh", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    setup = await client.ensure_seller_setup(marketplace_id="EBAY_US")
    await client.close()

    assert setup.opted_in is True
    assert setup.payment_policy_id == "pay-1"
    assert setup.return_policy_id == "ret-1"
    assert setup.fulfillment_policy_id == "ful-1"
    assert setup.merchant_location_key == "liquid-home"
    assert setup.created == ("return policy", "fulfillment policy", "location")
    assert ("POST", "/sell/account/v1/program/opt_in") in calls
    assert setup.env_values()["EBAY_SB_FULFILLMENT_POLICY_ID"] == "ful-1"


@pytest.mark.asyncio
async def test_token_request_falls_back_to_the_tokens_own_scopes() -> None:
    token_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            body = request.read().decode()
            token_bodies.append(body)
            if "scope=" in body:
                return httpx.Response(
                    400, json={"error": "invalid_scope", "error_description": "scope not granted"}
                )
            return httpx.Response(200, json={"access_token": "narrow-token", "expires_in": 7200})
        if request.url.path == "/sell/account/v1/program/get_opted_in_programs":
            assert request.headers["authorization"] == "Bearer narrow-token"
            return httpx.Response(200, json={"programs": [{"programType": SELLING_POLICY_PROGRAM}]})
        return httpx.Response(500)

    client = EbayAccountClient(
        "id", "secret", "refresh", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert await client.ensure_opted_in("EBAY_US") is True
    await client.close()
    assert len(token_bodies) == 2
    assert "scope=" in token_bodies[0] and "scope=" not in token_bodies[1]


@pytest.mark.asyncio
async def test_existing_location_is_reused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        if request.url.path == "/sell/inventory/v1/location/home" and request.method == "GET":
            return httpx.Response(200, json={"merchantLocationKey": "home"})
        return httpx.Response(500, json={"errors": [{"message": "should not be called"}]})

    client = EbayAccountClient(
        "id", "secret", "refresh", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    created = await client.ensure_location(
        "home", "EBAY_US", name="x", postal_code="94105", city="SF", state="CA"
    )
    await client.close()
    assert created is False
