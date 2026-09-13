from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from contextlib import suppress
from datetime import UTC, datetime
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.clock import utc_now
from app.mail.marketplace import MarketplaceEmailProcessor, parse_marketplace_email
from app.models import EmailConnection, SellerConversation

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)

log = logging.getLogger(__name__)


class GmailError(RuntimeError):
    pass


class GmailStateSigner:
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
        return f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"

    def loads(self, state: str, *, now: int | None = None) -> str:
        try:
            encoded, supplied = state.split(".", 1)
            expected = hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest()
            actual = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
            if not hmac.compare_digest(expected, actual):
                raise ValueError("invalid Gmail connection state")
            payload = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
            )
            issued_at = int(payload["iat"])
            seller_id = str(payload["seller_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid Gmail connection state") from exc
        age = (now or int(time.time())) - issued_at
        if age < 0 or age > self.max_age_seconds:
            raise ValueError("Gmail connection link expired")
        return seller_id


class GmailTokenCipher:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise GmailError("stored Gmail authorization could not be decrypted") from exc


def _load_client_config(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text())
        config = payload.get("web") or payload.get("installed")
        if not isinstance(config, dict):
            raise ValueError
        required = ("client_id", "client_secret", "auth_uri", "token_uri")
        if not all(isinstance(config.get(key), str) and config[key] for key in required):
            raise ValueError
        return config
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise GmailError("Gmail OAuth client JSON is missing or invalid") from exc


class GmailOAuthClient:
    def __init__(
        self,
        client_json_path: str,
        redirect_uri: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = _load_client_config(client_json_path)
        self.redirect_uri = redirect_uri
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.config["client_id"],
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(GMAIL_SCOPES),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{self.config['auth_uri']}?{query}"

    async def exchange_code(self, code: str) -> tuple[str, str, tuple[str, ...]]:
        response = await self._client.post(
            self.config["token_uri"],
            data={
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        if not response.is_success:
            raise GmailError(f"Gmail authorization failed ({response.status_code})")
        payload = response.json()
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise GmailError("Google did not return offline Gmail access")
        scope_value = payload.get("scope")
        scopes = tuple(scope_value.split()) if isinstance(scope_value, str) else GMAIL_SCOPES
        return access_token, refresh_token, scopes

    async def refresh_access_token(self, refresh_token: str) -> str:
        response = await self._client.post(
            self.config["token_uri"],
            data={
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if not response.is_success:
            raise GmailError(f"Gmail token refresh failed ({response.status_code})")
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailError("Google did not return a Gmail access token")
        return token

    async def get_profile(self, access_token: str) -> str:
        response = await self._client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if not response.is_success:
            raise GmailError(f"Gmail profile lookup failed ({response.status_code})")
        address = response.json().get("emailAddress")
        if not isinstance(address, str) or not address:
            raise GmailError("Google did not return the Gmail address")
        return address.lower()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _header_values(message: dict[str, Any]) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for header in (message.get("payload") or {}).get("headers") or []:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name:
            values.setdefault(name, []).append(value)
    return {name: "\n".join(items) for name, items in values.items()}


def _decode_body(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="replace"
        )
    except (ValueError, UnicodeDecodeError):
        return ""


def _message_body(payload: dict[str, Any]) -> str:
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        mime_type = str(part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if isinstance(data, str):
            decoded = _decode_body(data)
            if mime_type == "text/plain":
                plain.append(decoded)
            elif mime_type == "text/html":
                html.append(decoded)
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                visit(child)

    visit(payload)
    if plain:
        return "\n".join(plain)
    rendered = re.sub(r"<[^>]+>", " ", "\n".join(html))
    return re.sub(r"\s+", " ", unescape(rendered)).strip()


class GmailConnectionService:
    def __init__(
        self,
        *,
        engine: Engine,
        oauth: GmailOAuthClient,
        app_secret: str,
        adapter: BlueBubblesAdapter | None = None,
    ) -> None:
        self.engine = engine
        self.oauth = oauth
        self.signer = GmailStateSigner(app_secret)
        self.cipher = GmailTokenCipher(app_secret)
        self.adapter = adapter
        self.processor = MarketplaceEmailProcessor(engine)

    def authorization_url(self, seller_id: str) -> str:
        return self.oauth.authorization_url(self.signer.dumps(seller_id))

    def seller_id_for_state(self, state: str) -> str:
        return self.signer.loads(state)

    async def complete(self, state: str, code: str) -> EmailConnection:
        seller_id = self.signer.loads(state)
        access_token, refresh_token, scopes = await self.oauth.exchange_code(code)
        email_address = await self.oauth.get_profile(access_token)
        now = utc_now()
        with Session(self.engine) as session:
            connection = session.exec(
                select(EmailConnection).where(EmailConnection.seller_id == seller_id)
            ).first()
            if connection is None:
                connection = EmailConnection(
                    seller_id=seller_id,
                    email_address=email_address,
                    encrypted_refresh_token=self.cipher.encrypt(refresh_token),
                    scopes_json=list(scopes),
                    connected_at=now,
                    updated_at=now,
                    last_checked_at=now,
                )
            else:
                connection.email_address = email_address
                connection.encrypted_refresh_token = self.cipher.encrypt(refresh_token)
                connection.scopes_json = list(scopes)
                connection.updated_at = now
                connection.last_checked_at = now
            session.add(connection)
            session.commit()
            session.refresh(connection)
            return connection

    async def poll_once(self) -> int:
        with Session(self.engine) as session:
            connections = list(session.exec(select(EmailConnection)).all())
        detected = 0
        for connection in connections:
            try:
                detected += await self._poll_connection(connection)
            except Exception as exc:
                log.warning("Gmail poll failed for seller %s: %s", connection.seller_id, exc)
        return detected

    async def _poll_connection(self, connection: EmailConnection) -> int:
        checkpoint = utc_now()
        token = await self.oauth.refresh_access_token(
            self.cipher.decrypt(connection.encrypted_refresh_token)
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = await self.oauth._client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params={
                "q": "newer_than:30d (from:ebay.com OR from:facebookmail.com)",
                "maxResults": 100,
            },
        )
        if not response.is_success:
            raise GmailError(f"Gmail message listing failed ({response.status_code})")
        detected = 0
        for reference in response.json().get("messages") or []:
            message_id = reference.get("id")
            if not isinstance(message_id, str):
                continue
            full_response = await self.oauth._client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                headers=headers,
                params={"format": "full"},
            )
            if not full_response.is_success:
                continue
            message = full_response.json()
            received_at = datetime.fromtimestamp(
                int(message.get("internalDate") or 0) / 1000,
                tz=UTC,
            )
            if received_at <= connection.last_checked_at:
                continue
            message_headers = _header_values(message)
            parsed = parse_marketplace_email(
                sender=message_headers.get("from", ""),
                subject=message_headers.get("subject", ""),
                body=_message_body(message.get("payload") or {}),
                authentication_results=message_headers.get("authentication-results", ""),
            )
            if parsed is None:
                continue
            result = self.processor.process(
                seller_id=connection.seller_id,
                provider=f"gmail:{connection.seller_id}",
                message_id=message_id,
                parsed=parsed,
                received_at=received_at,
                wall_at=checkpoint,
            )
            if result.duplicate or not result.notification:
                continue
            detected += 1
            await self._notify(connection, result.notification, token, message_id)

        with Session(self.engine) as session:
            stored = session.get(EmailConnection, connection.id)
            if stored is not None:
                stored.last_checked_at = checkpoint
                stored.updated_at = checkpoint
                session.add(stored)
                session.commit()
        return detected

    async def _notify(
        self,
        connection: EmailConnection,
        text: str,
        access_token: str,
        source_message_id: str,
    ) -> None:
        if self.adapter is not None:
            with Session(self.engine) as session:
                conversation = session.exec(
                    select(SellerConversation).where(
                        SellerConversation.seller_id == connection.seller_id
                    )
                ).first()
            if conversation is not None:
                with suppress(Exception):
                    await self.adapter.send_text(
                        conversation.chat_guid,
                        text,
                        f"gmail-alert:{connection.seller_id}:{source_message_id}",
                    )

        message = EmailMessage()
        message["To"] = connection.email_address
        message["From"] = connection.email_address
        message["Subject"] = "Liquid marketplace alert"
        message.set_content(text)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        response = await self.oauth._client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        if not response.is_success:
            raise GmailError(f"Gmail alert send failed ({response.status_code})")

    async def send_alert(self, seller_id: str, subject: str, text: str) -> bool:
        with Session(self.engine) as session:
            connection = session.exec(
                select(EmailConnection).where(EmailConnection.seller_id == seller_id)
            ).first()
        if connection is None:
            return False
        token = await self.oauth.refresh_access_token(
            self.cipher.decrypt(connection.encrypted_refresh_token)
        )
        message = EmailMessage()
        message["To"] = connection.email_address
        message["From"] = connection.email_address
        message["Subject"] = subject[:200]
        message.set_content(text)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        response = await self.oauth._client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
        )
        if not response.is_success:
            raise GmailError(f"Gmail alert send failed ({response.status_code})")
        return True

    async def close(self) -> None:
        await self.oauth.close()


async def gmail_poll_loop(
    service: GmailConnectionService,
    *,
    interval_seconds: float,
    stop,
) -> None:
    while not stop.is_set():
        await service.poll_once()
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
