from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.ids import new_id
from app.ledger import write_decision
from app.models import (
    Buyer,
    DemandObs,
    Item,
    ItemStatus,
    Listing,
    ListingStatus,
    MarketplaceEmailEvent,
    Offer,
    OfferStatus,
    Outbox,
    SaleClaim,
    SaleClaimStatus,
)

OFFER_PATTERNS = (
    r"\byou (?:have|received|got) an offer\b",
    r"\bnew offer (?:on|for)\b",
    r"\bsent you an offer\b",
    r"\bmade an offer\b",
)
SOLD_PATTERNS = (
    r"\byou made the sale\b",
    r"\byour item (?:has )?sold\b",
    r"\bcongratulations,? your item sold\b",
)
AMOUNT_PATTERN = re.compile(r"(?<![\w])\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
EBAY_ID_PATTERN = re.compile(
    r"(?:item|listing)(?:\s+(?:id|number))?\s*[:#]?\s*([0-9]{9,14})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedMarketplaceEmail:
    marketplace: str
    kind: str
    sender: str
    subject: str
    body: str
    amount_cents: int | None
    external_reference: str | None
    source_authenticated: bool


@dataclass(frozen=True, slots=True)
class ProcessedMarketplaceEmail:
    duplicate: bool
    kind: str
    marketplace: str
    item_id: str | None
    item_title: str | None
    amount_cents: int | None
    status: str
    notification: str | None


def _sender_marketplace(sender: str) -> tuple[str | None, str]:
    address = parseaddr(sender)[1].strip().lower()
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    if domain == "ebay.com" or domain.endswith(".ebay.com"):
        return "ebay", domain
    if domain == "facebookmail.com" or domain.endswith(".facebookmail.com"):
        return "facebook", domain
    return None, domain


def _authenticated_marketplace(domain: str, authentication_results: str) -> bool:
    authentication = authentication_results.lower()
    passed = "dkim=pass" in authentication or "spf=pass" in authentication
    if not passed:
        return False
    if domain == "ebay.com" or domain.endswith(".ebay.com"):
        return "ebay.com" in authentication
    if domain == "facebookmail.com" or domain.endswith(".facebookmail.com"):
        return "facebookmail.com" in authentication or "facebook.com" in authentication
    return False


def _money_cents(text: str, kind: str) -> int | None:
    labels = (
        (r"(?:offer(?: amount)?|offered)\s*(?:is|of|:)?\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",)
        if kind == "offer"
        else (
            r"(?:sold for|sale price|order total|total)\s*(?:is|of|:)?\s*"
            r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        )
    )
    for pattern in labels:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(round(float(match.group(1).replace(",", "")) * 100))
    matches = AMOUNT_PATTERN.findall(text)
    if not matches:
        return None
    values = [int(round(float(value.replace(",", "")) * 100)) for value in matches]
    return values[0] if values else None


def parse_marketplace_email(
    *,
    sender: str,
    subject: str,
    body: str,
    authentication_results: str = "",
) -> ParsedMarketplaceEmail | None:
    """Parse known marketplace mail. The body is data and never treated as an instruction."""
    marketplace, domain = _sender_marketplace(sender)
    if marketplace is None:
        return None
    searchable = f"{subject}\n{body[:12000]}"
    lowered = searchable.lower()
    if any(re.search(pattern, lowered) for pattern in SOLD_PATTERNS):
        kind = "sold"
    elif any(re.search(pattern, lowered) for pattern in OFFER_PATTERNS):
        kind = "offer"
    else:
        return None
    external_match = EBAY_ID_PATTERN.search(searchable) if marketplace == "ebay" else None
    return ParsedMarketplaceEmail(
        marketplace=marketplace,
        kind=kind,
        sender=parseaddr(sender)[1].strip().lower(),
        subject=subject.strip()[:500],
        body=body[:12000],
        amount_cents=_money_cents(searchable, kind),
        external_reference=external_match.group(1) if external_match else None,
        source_authenticated=_authenticated_marketplace(domain, authentication_results),
    )


def _normalized_words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.lower())
        if len(word) > 1 and word not in {"the", "and", "for", "your", "item", "offer"}
    }


def _match_item(
    session: Session,
    seller_id: str,
    parsed: ParsedMarketplaceEmail,
) -> tuple[Item | None, float]:
    if parsed.external_reference:
        listing = session.exec(
            select(Listing).where(Listing.external_id == parsed.external_reference)
        ).first()
        if listing is not None:
            item = session.get(Item, listing.item_id)
            if item is not None and item.seller_id == seller_id:
                return item, 1.0

    haystack = _normalized_words(f"{parsed.subject} {parsed.body}")
    candidates = session.exec(select(Item).where(Item.seller_id == seller_id)).all()
    best: tuple[Item | None, float] = (None, 0)
    for item in candidates:
        if item.status in {ItemStatus.DONE, ItemStatus.EXPIRED, ItemStatus.CANCELLED}:
            continue
        title_words = _normalized_words(item.title)
        if not title_words:
            continue
        score = len(title_words & haystack) / len(title_words)
        if score > best[1]:
            best = (item, score)
    return best if best[1] >= 0.75 else (None, best[1])


def _display_amount(amount_cents: int | None) -> str:
    return f"${amount_cents / 100:,.2f}" if amount_cents is not None else "an unknown amount"


class MarketplaceEmailProcessor:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def process(
        self,
        *,
        seller_id: str,
        provider: str,
        message_id: str,
        parsed: ParsedMarketplaceEmail,
        received_at: datetime,
        wall_at: datetime,
    ) -> ProcessedMarketplaceEmail:
        with Session(self.engine) as session:
            existing = session.get(MarketplaceEmailEvent, (provider, message_id))
            if existing is not None:
                item = (
                    session.get(Item, existing.matched_item_id)
                    if existing.matched_item_id
                    else None
                )
                return ProcessedMarketplaceEmail(
                    duplicate=True,
                    kind=existing.kind,
                    marketplace=existing.marketplace,
                    item_id=existing.matched_item_id,
                    item_title=item.title if item else None,
                    amount_cents=existing.amount_cents,
                    status=existing.status,
                    notification=None,
                )

            item, confidence = _match_item(session, seller_id, parsed)
            status = "needs_confirmation"
            notification: str
            amount = parsed.amount_cents

            if (
                parsed.kind == "offer"
                and item is not None
                and amount is not None
                and parsed.source_authenticated
            ):
                buyer = Buyer(
                    handle=f"email:{parsed.marketplace}:{message_id}",
                    channel=parsed.marketplace,
                    close_reliability=0.97 if parsed.marketplace == "ebay" else 0.85,
                )
                session.add(buyer)
                session.flush()
                session.add(
                    Offer(
                        item_id=item.id,
                        buyer_id=buyer.id,
                        amount_cents=amount,
                        status=OfferStatus.OPEN,
                        created_at=received_at,
                    )
                )
                session.add(
                    DemandObs(
                        item_id=item.id,
                        channel=parsed.marketplace,
                        kind="offer",
                        sim_at=received_at,
                    )
                )
                status = "recorded"
                notification = (
                    f"New {parsed.marketplace} offer: {_display_amount(amount)} for {item.title}. "
                    "Reply STATUS to review it."
                )
            elif parsed.kind == "sold" and item is not None and parsed.source_authenticated:
                if amount is None:
                    listing = session.exec(
                        select(Listing).where(
                            Listing.item_id == item.id,
                            Listing.channel == parsed.marketplace,
                        )
                    ).first()
                    amount = listing.price_cents if listing else None
                if amount is not None:
                    self._confirm_sale(
                        session,
                        item=item,
                        marketplace=parsed.marketplace,
                        amount_cents=amount,
                        message_id=message_id,
                        external_reference=parsed.external_reference,
                        received_at=received_at,
                        wall_at=wall_at,
                    )
                    status = "applied"
                    notification = (
                        f"Sale detected on {parsed.marketplace}: {item.title} sold for "
                        f"{_display_amount(amount)}. Other active listings were ended."
                    )
                else:
                    notification = (
                        f"{parsed.marketplace.title()} says {item.title} sold, but I could not "
                        "verify the amount. Reply STATUS to review it."
                    )
            else:
                event_name = "sale" if parsed.kind == "sold" else "offer"
                notification = (
                    f"Possible {parsed.marketplace} {event_name} detected, but I could not safely "
                    "match it to one item. Open Liquid or reply STATUS to review it."
                )

            event = MarketplaceEmailEvent(
                provider=provider,
                message_id=message_id,
                seller_id=seller_id,
                marketplace=parsed.marketplace,
                kind=parsed.kind,
                sender=parsed.sender,
                subject=parsed.subject,
                amount_cents=amount,
                external_reference=parsed.external_reference,
                matched_item_id=item.id if item else None,
                match_confidence=confidence,
                source_authenticated=parsed.source_authenticated,
                status=status,
                received_at=received_at,
                processed_at=wall_at,
            )
            session.add(event)
            session.commit()
            return ProcessedMarketplaceEmail(
                duplicate=False,
                kind=parsed.kind,
                marketplace=parsed.marketplace,
                item_id=item.id if item else None,
                item_title=item.title if item else None,
                amount_cents=amount,
                status=status,
                notification=notification,
            )

    @staticmethod
    def _confirm_sale(
        session: Session,
        *,
        item: Item,
        marketplace: str,
        amount_cents: int,
        message_id: str,
        external_reference: str | None,
        received_at: datetime,
        wall_at: datetime,
    ) -> None:
        if item.status == ItemStatus.SOLD:
            return
        active_claim = session.exec(
            select(SaleClaim).where(
                SaleClaim.item_id == item.id,
                SaleClaim.status == SaleClaimStatus.ACTIVE,
            )
        ).first()
        if active_claim is None:
            buyer = Buyer(
                handle=f"sale-email:{marketplace}:{message_id}",
                channel=marketplace,
                close_reliability=1,
            )
            session.add(buyer)
            session.flush()
            offer = Offer(
                item_id=item.id,
                buyer_id=buyer.id,
                amount_cents=amount_cents,
                status=OfferStatus.ACCEPTED,
                created_at=received_at,
            )
            session.add(offer)
            session.flush()
            active_claim = SaleClaim(
                item_id=item.id,
                offer_id=offer.id,
                channel=marketplace,
                amount_cents=amount_cents,
                status=SaleClaimStatus.CONFIRMED,
                external_reference=external_reference or message_id,
                claimed_at=received_at,
                resolved_at=received_at,
                resolution_source="authenticated_marketplace_email",
            )
        else:
            active_claim.status = SaleClaimStatus.CONFIRMED
            active_claim.amount_cents = amount_cents
            active_claim.external_reference = external_reference or message_id
            active_claim.resolved_at = received_at
            active_claim.resolution_source = "authenticated_marketplace_email"
        session.add(active_claim)
        item.status = ItemStatus.SOLD
        session.add(item)
        listings = session.exec(select(Listing).where(Listing.item_id == item.id)).all()
        for listing in listings:
            listing.status = ListingStatus.ENDED
            session.add(listing)
        action_id = new_id()
        session.add(
            Outbox(
                kind="end_other_listings",
                payload_json={"item_id": item.id, "sold_channel": marketplace},
                idempotency_key=f"{item.id}:{action_id}:end_other_listings",
            )
        )
        write_decision(
            session,
            item_id=item.id,
            sim_at=received_at,
            wall_at=wall_at,
            kind="marketplace_email",
            action="confirm_sale",
            inputs={
                "marketplace": marketplace,
                "message_id": message_id,
                "external_reference": external_reference,
            },
            reason="authenticated marketplace email confirmed the sale",
            price_before=None,
            price_after=amount_cents,
        )
