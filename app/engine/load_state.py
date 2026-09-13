from __future__ import annotations

from sqlmodel import Session, select

from app.clock import as_utc
from app.engine.state import ChannelState, CheckoutState, ItemState, StandingOffer, default_channels
from app.models import (
    Buyer,
    Checkout,
    CheckoutStatus,
    DemandObs,
    Item,
    Listing,
    ListingStatus,
    Offer,
    OfferStatus,
)


def load_state(session: Session, item_id: str) -> ItemState:
    item = session.get(Item, item_id)
    if item is None:
        raise LookupError(f"item not found: {item_id}")

    listing = session.exec(
        select(Listing).where(Listing.item_id == item_id, Listing.status == ListingStatus.LIVE)
    ).first()
    offer_rows = session.exec(
        select(Offer).where(
            Offer.item_id == item_id,
            Offer.status.in_([OfferStatus.OPEN, OfferStatus.COUNTERED]),
        )
    ).all()
    offers: list[StandingOffer] = []
    for offer in offer_rows:
        buyer = session.get(Buyer, offer.buyer_id)
        if buyer is None:
            continue
        offers.append(
            StandingOffer(
                id=offer.id,
                buyer_id=offer.buyer_id,
                amount_cents=offer.amount_cents,
                channel=buyer.channel,
                pay_reliability=buyer.pay_reliability,
                settlement_hours=0.1 if buyer.channel == "local" else 96,
                answered=offer.status == OfferStatus.COUNTERED,
                buyer_failed=buyer.failed_count > 0,
            )
        )

    checkout_row = session.exec(
        select(Checkout).where(
            Checkout.item_id == item_id,
            Checkout.status == CheckoutStatus.OPEN,
        )
    ).first()
    checkout = None
    if checkout_row is not None:
        checkout = CheckoutState(
            id=checkout_row.id,
            buyer_id=checkout_row.buyer_id,
            amount_cents=checkout_row.amount_cents,
            window_ends_at=as_utc(checkout_row.window_ends_at),
        )

    observations = session.exec(select(DemandObs).where(DemandObs.item_id == item_id)).all()
    elapsed_hours = max(
        0,
        max(
            (
                (as_utc(obs.sim_at) - as_utc(item.created_at)).total_seconds() / 3600
                for obs in observations
            ),
            default=0,
        ),
    )
    channels: list[ChannelState] = []
    for baseline in default_channels():
        matching = [obs for obs in observations if obs.channel == baseline.name]
        channels.append(
            ChannelState(
                name=baseline.name,
                prior_alpha=baseline.prior_alpha,
                prior_beta_hours=baseline.prior_beta_hours,
                elapsed_hours=elapsed_hours,
                inquiries=sum(obs.value for obs in matching if obs.kind in {"inquiry", "offer"}),
                views=round(sum(obs.value for obs in matching if obs.kind == "view")),
            )
        )

    constraints = item.constraints_json
    return ItemState(
        item_id=item.id,
        status=item.status,
        deadline_at=as_utc(item.deadline_at),
        original_horizon_hours=item.original_horizon_hours,
        floor_cents=item.floor_cents,
        market_value_cents=item.market_value_cents,
        sigma_cents=item.sigma_cents,
        instant_quote_cents=item.instant_quote_cents,
        instant_ok=bool(constraints.get("instant_ok", True)),
        instant_preauthorized=item.instant_preauthorized,
        current_price_cents=listing.price_cents if listing else None,
        last_reprice_at=as_utc(listing.last_reprice_at)
        if listing and listing.last_reprice_at
        else None,
        escalated_at=as_utc(item.escalated_at) if item.escalated_at else None,
        channels=tuple(channels),
        offers=tuple(offers),
        checkout=checkout,
        interested_buyer_ids=tuple(dict.fromkeys(offer.buyer_id for offer in offer_rows)),
    )
