from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Any, Protocol
from urllib.parse import quote
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import httpx

BASE_SCOPE = "https://api.ebay.com/oauth/api_scope"
SELL_INVENTORY_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"
SELL_ACCOUNT_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.account"
TRADING_COMPATIBILITY_LEVEL = "967"
EBAY_XML_NS = "urn:ebay:apis:eBLBaseComponents"
MEDIA_API_BASE_URL = "https://apim.ebay.com"

log = logging.getLogger(__name__)


class EbayError(RuntimeError):
    """An eBay API failure; carries the HTTP status and eBay error id when known."""

    def __init__(
        self, message: str, *, status_code: int | None = None, error_id: int | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_id = error_id


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


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        environment: str = "production",
        client: httpx.AsyncClient | None = None,
        scopes: tuple[str, ...] = (SELL_INVENTORY_SCOPE,),
    ) -> None:
        if environment not in {"sandbox", "production"}:
            raise ValueError("environment must be sandbox or production")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.environment = environment
        self.scopes = scopes
        host = "api.sandbox.ebay.com" if environment == "sandbox" else "api.ebay.com"
        self.api_base_url = f"https://{host}"
        self.token_url = f"https://{host}/identity/v1/oauth2/token"
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def access_token(self) -> str:
        """A valid user access token (minted from the refresh token, cached until expiry)."""
        return await self._get_access_token()

    async def _mint_token(self, scope: str | None) -> httpx.Response:
        data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        if scope:
            data["scope"] = scope
        return await self._client.post(
            self.token_url,
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )

    async def _get_access_token(self) -> str:
        if self._access_token and monotonic() < self._access_token_expires_at:
            return self._access_token
        response = await self._mint_token(" ".join(self.scopes) if self.scopes else None)
        if response.status_code == 400 and self.scopes:
            # The refresh token was granted a narrower scope set than requested: eBay then
            # returns invalid_scope. Fall back to whatever scopes the token actually carries.
            log.info("eBay refused the requested scopes; retrying with the token's own scopes")
            response = await self._mint_token(None)
        self._raise_for_status(response, "eBay authorization failed")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise EbayError("eBay authorization response did not contain an access token")
        self._access_token = token
        expires_in = response.json().get("expires_in", 7200)
        lifetime = expires_in if isinstance(expires_in, int) else 7200
        self._access_token_expires_at = monotonic() + max(lifetime - 60, 0)
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
        error_id: int | None = None
        try:
            payload = response.json()
            errors = payload.get("errors") or []
            if errors and isinstance(errors[0], dict):
                message = errors[0].get("message")
                if isinstance(message, str) and message:
                    detail = message
                long_message = errors[0].get("longMessage")
                if isinstance(long_message, str) and long_message and long_message != detail:
                    detail = f"{detail} {long_message}"
                if isinstance(errors[0].get("errorId"), int):
                    error_id = errors[0]["errorId"]
            elif isinstance(payload.get("error_description"), str):
                detail = payload["error_description"]
        except (ValueError, AttributeError):
            pass
        raise EbayError(
            f"{detail} ({response.status_code})",
            status_code=response.status_code,
            error_id=error_id,
        )

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

    async def withdraw(self, offer_id: str, marketplace_id: str) -> None:
        """End the live listing behind an offer (the offer itself stays, unpublished)."""
        await self._request(
            "POST",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}/withdraw",
            marketplace_id=marketplace_id,
        )

    async def delete_offer(self, offer_id: str, marketplace_id: str) -> None:
        await self._request(
            "DELETE",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}",
            marketplace_id=marketplace_id,
        )

    async def delete_inventory_item(self, sku: str, marketplace_id: str) -> None:
        await self._request(
            "DELETE",
            f"/sell/inventory/v1/inventory_item/{quote(sku, safe='')}",
            marketplace_id=marketplace_id,
        )

    async def upload_picture(
        self,
        content: bytes,
        *,
        filename: str = "photo.jpg",
        mime_type: str = "image/jpeg",
        picture_name: str | None = None,
    ) -> str:
        """Host a photo on eBay Picture Services and return its public URL.

        The sandbox only supports the Trading API upload (retired 2026-09-30); production uses the
        Media API. Either way the returned URL is what the Inventory API expects in imageUrls, so
        listings no longer need a public tunnel back to this machine.
        """
        if not content:
            raise EbayError("cannot upload an empty picture")
        if self.environment == "production":
            return await self._upload_picture_media_api(content, filename, mime_type)
        return await self._upload_picture_trading_api(content, filename, mime_type, picture_name)

    async def _upload_picture_trading_api(
        self, content: bytes, filename: str, mime_type: str, picture_name: str | None
    ) -> str:
        token = await self._get_access_token()
        name = escape(picture_name or filename)
        payload = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<UploadSiteHostedPicturesRequest xmlns="{EBAY_XML_NS}">'
            f"<PictureName>{name}</PictureName>"
            "<PictureSet>Standard</PictureSet>"
            "</UploadSiteHostedPicturesRequest>"
        )
        response = await self._client.post(
            f"{self.api_base_url}/ws/api.dll",
            headers={
                "X-EBAY-API-IAF-TOKEN": token,
                "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPATIBILITY_LEVEL,
                "X-EBAY-API-RESPONSE-ENCODING": "XML",
                "X-EBAY-API-DETAIL-LEVEL": "0",
            },
            data={"XML Payload": payload},
            files={"image": (filename, content, mime_type)},
        )
        if not response.is_success:
            raise EbayError(
                f"eBay picture upload failed ({response.status_code})",
                status_code=response.status_code,
            )
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise EbayError("eBay picture upload returned unreadable XML") from exc
        ns = {"e": EBAY_XML_NS}
        ack = (root.findtext("e:Ack", namespaces=ns) or "").strip()
        url = (root.findtext("e:SiteHostedPictureDetails/e:FullURL", namespaces=ns) or "").strip()
        if ack not in {"Success", "Warning"} or not url:
            messages = [
                (node.text or "").strip()
                for node in root.findall("e:Errors/e:LongMessage", namespaces=ns)
            ]
            detail = "; ".join(message for message in messages if message)
            raise EbayError(f"eBay picture upload failed: {detail or ack or 'no picture URL'}")
        return url

    async def _upload_picture_media_api(self, content: bytes, filename: str, mime_type: str) -> str:
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        created = await self._client.post(
            f"{MEDIA_API_BASE_URL}/commerce/media/v1_beta/image/create_image_from_file",
            headers=headers,
            files={"image": (filename, content, mime_type)},
        )
        self._raise_for_status(created, "eBay picture upload failed")
        location = created.headers.get("location", "")
        image_id = location.rstrip("/").rsplit("/", 1)[-1] if location else ""
        if not image_id:
            raise EbayError("eBay picture upload did not return an image location")
        fetched = await self._client.get(
            f"{MEDIA_API_BASE_URL}/commerce/media/v1_beta/image/{quote(image_id, safe='')}",
            headers=headers,
        )
        self._raise_for_status(fetched, "eBay picture lookup failed")
        url = fetched.json().get("imageUrl")
        if not isinstance(url, str) or not url:
            raise EbayError("eBay picture lookup did not return an image URL")
        return url


class EbaySandboxClient(EbayClient):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        scopes: tuple[str, ...] = (SELL_INVENTORY_SCOPE,),
    ) -> None:
        super().__init__(
            client_id,
            client_secret,
            refresh_token,
            environment="sandbox",
            client=client,
            scopes=scopes,
        )
