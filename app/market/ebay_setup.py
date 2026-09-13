"""One-shot eBay seller setup: business-policy opt-in, the three policies, and a location.

Every offer the Inventory API publishes must reference a payment, return, and fulfillment policy
plus a merchant location. Creating those by hand in the sandbox UI is where teams stall, so this
module makes it idempotent: existing policies are found by name, existing locations by key, and
only the missing pieces are created.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.market.ebay import SELL_ACCOUNT_SCOPE, SELL_INVENTORY_SCOPE, EbayClient, EbayError

SELLING_POLICY_PROGRAM = "SELLING_POLICY_MANAGEMENT"
NON_MOTORS = {"name": "ALL_EXCLUDING_MOTORS_VEHICLES", "default": True}
POLICY_KINDS = ("payment", "return", "fulfillment")
POLICY_ID_FIELDS = {
    "payment": "paymentPolicyId",
    "return": "returnPolicyId",
    "fulfillment": "fulfillmentPolicyId",
}


@dataclass(frozen=True, slots=True)
class SellerSetup:
    merchant_location_key: str
    payment_policy_id: str
    return_policy_id: str
    fulfillment_policy_id: str
    opted_in: bool
    created: tuple[str, ...] = field(default_factory=tuple)

    def env_values(self) -> dict[str, str]:
        return {
            "EBAY_SB_MERCHANT_LOCATION_KEY": self.merchant_location_key,
            "EBAY_SB_PAYMENT_POLICY_ID": self.payment_policy_id,
            "EBAY_SB_RETURN_POLICY_ID": self.return_policy_id,
            "EBAY_SB_FULFILLMENT_POLICY_ID": self.fulfillment_policy_id,
        }


def payment_policy_body(name: str, marketplace_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "marketplaceId": marketplace_id,
        "categoryTypes": [NON_MOTORS],
        "immediatePay": True,
    }


def return_policy_body(name: str, marketplace_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "marketplaceId": marketplace_id,
        "categoryTypes": [NON_MOTORS],
        "returnsAccepted": True,
        "returnPeriod": {"value": 30, "unit": "DAY"},
        "returnShippingCostPayer": "BUYER",
        "refundMethod": "MONEY_BACK",
    }


def fulfillment_policy_body(name: str, marketplace_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "marketplaceId": marketplace_id,
        "categoryTypes": [NON_MOTORS],
        "handlingTime": {"value": 1, "unit": "DAY"},
        "shippingOptions": [
            {
                "costType": "FLAT_RATE",
                "optionType": "DOMESTIC",
                "shippingServices": [
                    {
                        "shippingCarrierCode": "USPS",
                        "shippingServiceCode": "USPSPriority",
                        "freeShipping": True,
                        "sortOrder": 1,
                    }
                ],
            }
        ],
    }


POLICY_BODIES = {
    "payment": payment_policy_body,
    "return": return_policy_body,
    "fulfillment": fulfillment_policy_body,
}


def location_body(
    *, name: str, postal_code: str, city: str, state: str, country: str
) -> dict[str, Any]:
    return {
        "location": {
            "address": {
                "city": city,
                "stateOrProvince": state,
                "postalCode": postal_code,
                "country": country,
            }
        },
        "locationTypes": ["WAREHOUSE"],
        "merchantLocationStatus": "ENABLED",
        "name": name,
    }


class EbayAccountClient(EbayClient):
    """EbayClient plus the Account API calls needed to make a seller publish-ready."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        environment: str = "sandbox",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            client_id,
            client_secret,
            refresh_token,
            environment=environment,
            client=client,
            scopes=(SELL_INVENTORY_SCOPE, SELL_ACCOUNT_SCOPE),
        )

    # ---------- business policy program ----------
    async def opted_in_programs(self, marketplace_id: str) -> set[str]:
        response = await self._request(
            "GET", "/sell/account/v1/program/get_opted_in_programs", marketplace_id=marketplace_id
        )
        programs = response.json().get("programs") or []
        return {
            str(program.get("programType"))
            for program in programs
            if isinstance(program, dict) and program.get("programType")
        }

    async def ensure_opted_in(self, marketplace_id: str) -> bool:
        """Opt the seller into business policies; True when the program is active."""
        if SELLING_POLICY_PROGRAM in await self.opted_in_programs(marketplace_id):
            return True
        await self._request(
            "POST",
            "/sell/account/v1/program/opt_in",
            marketplace_id=marketplace_id,
            json={"programType": SELLING_POLICY_PROGRAM},
        )
        return SELLING_POLICY_PROGRAM in await self.opted_in_programs(marketplace_id)

    # ---------- policies ----------
    async def find_policy(self, kind: str, name: str, marketplace_id: str) -> str | None:
        try:
            response = await self._request(
                "GET",
                f"/sell/account/v1/{kind}_policy/get_by_policy_name"
                f"?marketplace_id={marketplace_id}&name={httpx.URL(name).path or name}",
                marketplace_id=marketplace_id,
            )
        except EbayError as exc:
            if exc.status_code == 404:
                return None
            raise
        policy_id = response.json().get(POLICY_ID_FIELDS[kind])
        return str(policy_id) if policy_id else None

    async def policy_exists(self, kind: str, policy_id: str, marketplace_id: str) -> bool:
        try:
            await self._request(
                "GET",
                f"/sell/account/v1/{kind}_policy/{httpx.URL(policy_id).path or policy_id}",
                marketplace_id=marketplace_id,
            )
        except EbayError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    async def create_policy(self, kind: str, body: dict[str, Any], marketplace_id: str) -> str:
        response = await self._request(
            "POST", f"/sell/account/v1/{kind}_policy", marketplace_id=marketplace_id, json=body
        )
        policy_id = response.json().get(POLICY_ID_FIELDS[kind])
        if not policy_id:
            raise EbayError(f"eBay did not return a {kind} policy id")
        return str(policy_id)

    async def ensure_policy(
        self, kind: str, name: str, marketplace_id: str
    ) -> tuple[str, bool]:
        existing = await self.find_policy(kind, name, marketplace_id)
        if existing:
            return existing, False
        body = POLICY_BODIES[kind](name, marketplace_id)
        try:
            return await self.create_policy(kind, body, marketplace_id), True
        except EbayError as exc:
            # A duplicate-name race: the policy now exists, so look it up again.
            if exc.status_code == 400 and "name" in str(exc).lower():
                found = await self.find_policy(kind, name, marketplace_id)
                if found:
                    return found, False
            raise

    # ---------- inventory location ----------
    async def location_exists(self, key: str, marketplace_id: str) -> bool:
        try:
            await self._request(
                "GET",
                f"/sell/inventory/v1/location/{httpx.URL(key).path or key}",
                marketplace_id=marketplace_id,
            )
        except EbayError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    async def create_location(
        self, key: str, body: dict[str, Any], marketplace_id: str
    ) -> None:
        try:
            await self._request(
                "POST",
                f"/sell/inventory/v1/location/{httpx.URL(key).path or key}",
                marketplace_id=marketplace_id,
                json=body,
            )
        except EbayError as exc:
            if exc.status_code == 409:  # 25803: a location with this key already exists
                return
            raise

    async def ensure_location(
        self,
        key: str,
        marketplace_id: str,
        *,
        name: str,
        postal_code: str,
        city: str,
        state: str,
        country: str = "US",
    ) -> bool:
        if await self.location_exists(key, marketplace_id):
            return False
        await self.create_location(
            key,
            location_body(
                name=name, postal_code=postal_code, city=city, state=state, country=country
            ),
            marketplace_id,
        )
        return True

    # ---------- everything ----------
    async def ensure_seller_setup(
        self,
        *,
        marketplace_id: str,
        location_key: str = "liquid-home",
        policy_prefix: str = "Liquid",
        postal_code: str = "94105",
        city: str = "San Francisco",
        state: str = "CA",
        country: str = "US",
    ) -> SellerSetup:
        opted_in = await self.ensure_opted_in(marketplace_id)
        if not opted_in:
            raise EbayError(
                "eBay accepted the business-policy opt-in but has not activated it yet; "
                "wait a few minutes and run the setup again"
            )
        created: list[str] = []
        ids: dict[str, str] = {}
        for kind in POLICY_KINDS:
            policy_id, was_created = await self.ensure_policy(
                kind, f"{policy_prefix} {kind} policy", marketplace_id
            )
            ids[kind] = policy_id
            if was_created:
                created.append(f"{kind} policy")
        if await self.ensure_location(
            location_key,
            marketplace_id,
            name=f"{policy_prefix} ship-from",
            postal_code=postal_code,
            city=city,
            state=state,
            country=country,
        ):
            created.append("location")
        return SellerSetup(
            merchant_location_key=location_key,
            payment_policy_id=ids["payment"],
            return_policy_id=ids["return"],
            fulfillment_policy_id=ids["fulfillment"],
            opted_in=opted_in,
            created=tuple(created),
        )
