from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote

import httpx

SELL_INVENTORY_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"


class EbayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EbayOfferInput:
    sku: str
    title: str
    description: str
    condition: str
    aspects: dict[str, list[str]]
    image_urls: list[str]
    category_id: str
    marketplace_id: str
    currency: str
    price_cents: int
    merchant_location_key: str
    payment_policy_id: str
    return_policy_id: str
    fulfillment_policy_id: str


@dataclass(frozen=True, slots=True)
class EbayDraft:
    offer_id: str
    sku: str


@dataclass(frozen=True, slots=True)
class EbayPublication:
    offer_id: str
    listing_id: str


class EbayPublisher(Protocol):
    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft: ...

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication: ...

    async def close(self) -> None: ...


class EbayRepricer(Protocol):
    async def update_price(
        self, *, sku: str, offer_id: str, price_cents: int, currency: str, marketplace_id: str
    ) -> None: ...


class EbaySandboxClient:
    api_base_url = "https://api.sandbox.ebay.com"
    token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self._access_token: str | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        response = await self._client.post(
            self.token_url,
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": SELL_INVENTORY_SCOPE,
            },
        )
        self._raise_for_status(response, "eBay authorization failed")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise EbayError("eBay authorization response did not contain an access token")
        self._access_token = token
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        marketplace_id: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._get_access_token()
        response = await self._client.request(
            method,
            f"{self.api_base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Language": "en-US",
                "Content-Type": "application/json",
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            },
            json=json,
        )
        self._raise_for_status(response, "eBay Inventory API request failed")
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, fallback: str) -> None:
        if response.is_success:
            return
        detail = fallback
        try:
            payload = response.json()
            errors = payload.get("errors") or []
            if errors and isinstance(errors[0], dict):
                message = errors[0].get("message")
                if isinstance(message, str) and message:
                    detail = message
            elif isinstance(payload.get("error_description"), str):
                detail = payload["error_description"]
        except (ValueError, AttributeError):
            pass
        raise EbayError(f"{detail} ({response.status_code})")

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        if not offer.image_urls:
            raise EbayError("at least one seller-approved image is required")
        sku = quote(offer.sku, safe="")
        await self._request(
            "PUT",
            f"/sell/inventory/v1/inventory_item/{sku}",
            marketplace_id=offer.marketplace_id,
            json={
                "availability": {"shipToLocationAvailability": {"quantity": 1}},
                "condition": offer.condition,
                "conditionDescription": offer.description,
                "product": {
                    "title": offer.title,
                    "description": offer.description,
                    "aspects": offer.aspects,
                    "imageUrls": offer.image_urls,
                },
            },
        )
        price = str((Decimal(offer.price_cents) / Decimal(100)).quantize(Decimal("0.01")))
        response = await self._request(
            "POST",
            "/sell/inventory/v1/offer",
            marketplace_id=offer.marketplace_id,
            json={
                "sku": offer.sku,
                "marketplaceId": offer.marketplace_id,
                "format": "FIXED_PRICE",
                "availableQuantity": 1,
                "categoryId": offer.category_id,
                "listingDescription": offer.description,
                "listingDuration": "GTC",
                "listingPolicies": {
                    "paymentPolicyId": offer.payment_policy_id,
                    "returnPolicyId": offer.return_policy_id,
                    "fulfillmentPolicyId": offer.fulfillment_policy_id,
                },
                "merchantLocationKey": offer.merchant_location_key,
                "pricingSummary": {"price": {"currency": offer.currency, "value": price}},
            },
        )
        offer_id = response.json().get("offerId")
        if not isinstance(offer_id, str) or not offer_id:
            raise EbayError("eBay draft response did not contain an offer ID")
        return EbayDraft(offer_id=offer_id, sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        response = await self._request(
            "POST",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}/publish",
            marketplace_id=marketplace_id,
        )
        listing_id = response.json().get("listingId")
        if not isinstance(listing_id, str) or not listing_id:
            raise EbayError("eBay publish response did not contain a listing ID")
        return EbayPublication(offer_id=offer_id, listing_id=listing_id)

    async def update_price(
        self, *, sku: str, offer_id: str, price_cents: int, currency: str, marketplace_id: str
    ) -> None:
        """Change a live offer's price without resending the offer (bulkUpdatePriceQuantity)."""
        price = str((Decimal(price_cents) / Decimal(100)).quantize(Decimal("0.01")))
        response = await self._request(
            "POST",
            "/sell/inventory/v1/bulk_update_price_quantity",
            marketplace_id=marketplace_id,
            json={
                "requests": [
                    {
                        "sku": sku,
                        "offers": [
                            {"offerId": offer_id, "price": {"currency": currency, "value": price}}
                        ],
                    }
                ]
            },
        )
        for entry in response.json().get("responses", []):
            status = entry.get("statusCode")
            if isinstance(status, int) and status >= 400:
                errors = entry.get("errors") or [{}]
                raise EbayError(str(errors[0].get("message") or f"price update failed ({status})"))
