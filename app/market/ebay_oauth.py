from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.clock import utc_now
from app.market.ebay import EbayClient, EbayError, EbayPublisher
from app.models import EbayConnection

EBAY_OAUTH_SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
)


@dataclass(frozen=True, slots=True)
class EbayTokenSet:
    refresh_token: str
    scopes: tuple[str, ...]


class EbayStateSigner:
    def __init__(self, secret: str, *, max_age_seconds: int = 600) -> None:
        if len(secret) < 32:
            raise ValueError("APP_SECRET must be at least 32 characters")
        self.secret = secret.encode()
        self.max_age_seconds = max_age_seconds

    def dumps(self, seller_id: str, *, now: int | None = None) -> str:
        payload = json.dumps(
            {
                "seller_id": seller_id,
                "iat": now or int(time.time()),
                "nonce": secrets.token_urlsafe(12),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        return f"{encoded}.{encoded_signature}"

    def loads(self, state: str, *, now: int | None = None) -> str:
        try:
            encoded, supplied_signature = state.split(".", 1)
            expected = hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest()
            padding = "=" * (-len(supplied_signature) % 4)
            actual = base64.urlsafe_b64decode(supplied_signature + padding)
            if not hmac.compare_digest(expected, actual):
                raise ValueError("invalid eBay connection state")
            payload = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
            )
            issued_at = int(payload["iat"])
            seller_id = str(payload["seller_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid eBay connection state") from exc
        age = (now or int(time.time())) - issued_at
        if age < 0 or age > self.max_age_seconds:
            raise ValueError("eBay connection link expired")
        return seller_id


class TokenCipher:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise EbayError("stored eBay authorization could not be decrypted") from exc


class EbayOAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        runame: str,
        *,
        environment: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.runame = runame
        self.environment = environment
        auth_host = "auth.sandbox.ebay.com" if environment == "sandbox" else "auth.ebay.com"
        api_host = "api.sandbox.ebay.com" if environment == "sandbox" else "api.ebay.com"
        self.authorization_endpoint = f"https://{auth_host}/oauth2/authorize"
        self.token_endpoint = f"https://{api_host}/identity/v1/oauth2/token"
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.runame,
                "response_type": "code",
                "scope": " ".join(EBAY_OAUTH_SCOPES),
                "state": state,
            }
        )
        return f"{self.authorization_endpoint}?{query}"

    async def exchange_code(self, code: str) -> EbayTokenSet:
        response = await self._client.post(
            self.token_endpoint,
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": self.runame},
        )
        if not response.is_success:
            raise EbayError(f"eBay authorization failed ({response.status_code})")
        payload: dict[str, Any] = response.json()
        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise EbayError("eBay did not return a refresh token")
        scope_value = payload.get("scope")
        scopes = tuple(scope_value.split()) if isinstance(scope_value, str) else EBAY_OAUTH_SCOPES
        return EbayTokenSet(refresh_token=refresh_token, scopes=scopes)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class EbayConnectionService:
    def __init__(
        self,
        *,
        engine: Engine,
        oauth: EbayOAuthClient,
        app_secret: str,
    ) -> None:
        self.engine = engine
        self.oauth = oauth
        self.signer = EbayStateSigner(app_secret)
        self.cipher = TokenCipher(app_secret)
        self._publishers: dict[str, EbayClient] = {}

    def authorization_url(self, seller_id: str) -> str:
        return self.oauth.authorization_url(self.signer.dumps(seller_id))

    def seller_id_for_state(self, state: str) -> str:
        return self.signer.loads(state)

    async def complete(self, state: str, code: str) -> EbayConnection:
        seller_id = self.signer.loads(state)
        tokens = await self.oauth.exchange_code(code)
        now = utc_now()
        with Session(self.engine) as session:
            connection = session.exec(
                select(EbayConnection).where(EbayConnection.seller_id == seller_id)
            ).first()
            if connection is None:
                connection = EbayConnection(
                    seller_id=seller_id,
                    environment=self.oauth.environment,
                    encrypted_refresh_token=self.cipher.encrypt(tokens.refresh_token),
                    scopes_json=list(tokens.scopes),
                    connected_at=now,
                    updated_at=now,
                )
            else:
                connection.environment = self.oauth.environment
                connection.encrypted_refresh_token = self.cipher.encrypt(tokens.refresh_token)
                connection.scopes_json = list(tokens.scopes)
                connection.updated_at = now
            session.add(connection)
            session.commit()
            session.refresh(connection)
        old = self._publishers.pop(seller_id, None)
        if old is not None:
            await old.close()
        return connection

    def publisher_for(self, seller_id: str) -> EbayPublisher | None:
        existing = self._publishers.get(seller_id)
        if existing is not None:
            return existing
        with Session(self.engine) as session:
            connection = session.exec(
                select(EbayConnection).where(EbayConnection.seller_id == seller_id)
            ).first()
        if connection is None:
            return None
        if connection.environment == "demo":
            return None
        publisher = EbayClient(
            self.oauth.client_id,
            self.oauth.client_secret,
            self.cipher.decrypt(connection.encrypted_refresh_token),
            environment=connection.environment,
        )
        self._publishers[seller_id] = publisher
        return publisher

    async def close(self) -> None:
        await self.oauth.close()
        for publisher in self._publishers.values():
            await publisher.close()
        self._publishers.clear()
