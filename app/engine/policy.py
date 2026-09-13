from __future__ import annotations

import math
from datetime import datetime

from app.engine.actions import (
    Accept,
    Action,
    Counter,
    Escalate,
    Expire,
    Hold,
    PaymentTimeout,
    Reprice,
    RouteInstant,
)
from app.engine.demand import (
    accept_expected_value_cents,
    optimal_price,
    rank_prices,
)
from app.engine.state import ItemState, StandingOffer
from app.market.fees import net_proceeds_cents
from app.models import ItemStatus


def hours_until(deadline: datetime, now: datetime) -> float:
    return (deadline - now).total_seconds() / 3600


def escalation_hours(state: ItemState) -> float:
    return max(2, state.original_horizon_hours * 0.05)


def counter_price_cents(
    state: ItemState,
    offer: StandingOffer,
    continuation_value_cents: float,
) -> int:
    ceiling = state.current_price_cents or math.floor(state.market_value_cents * 1.3 / 100) * 100
    target = ceiling
    for price in range(state.floor_cents, ceiling + 1, 100):
        if (
            offer.pay_reliability * net_proceeds_cents(offer.channel, price)
            >= continuation_value_cents
        ):
            target = price
            break
    rounded = math.ceil(target / 500) * 500
    return max(state.floor_cents, min(rounded, ceiling))


def should_reprice(state: ItemState, target_cents: int, now: datetime) -> bool:
    if state.current_price_cents is None:
        return False
    minimum_drop = max(300, round(state.current_price_cents * 0.02))
    if target_cents > state.current_price_cents - minimum_drop:
        return False
    minimum_interval_hours = max(1, state.original_horizon_hours / 12)
    if state.last_reprice_at is None:
        return True
    elapsed = (now - state.last_reprice_at).total_seconds() / 3600
    return elapsed >= minimum_interval_hours


def _inputs(state: ItemState, tau: float) -> dict:
    ranking = rank_prices(state, max(0, tau))[:3]
    return {
        "market_value_cents": state.market_value_cents,
        "sigma_cents": state.sigma_cents,
        "floor_cents": state.floor_cents,
        "hours_left": round(tau, 4),
        "current_price_cents": state.current_price_cents,
        "arrival_rates_per_hour": {
            channel.name: round(
                (channel.prior_alpha + channel.inquiries + 0.05 * channel.views)
                / (channel.prior_beta_hours + channel.elapsed_hours),
                6,
            )
            for channel in state.channels
        },
        "top_candidates": [
            {
                "price_cents": row.price_cents,
                "expected_value_cents": round(row.expected_value_cents, 2),
                "sale_probability": round(row.sale_probability, 6),
            }
            for row in ranking
        ],
        "standing_offers": [
            {
                "offer_id": offer.id,
                "amount_cents": offer.amount_cents,
                "buyer_id": offer.buyer_id,
                "pay_reliability": offer.pay_reliability,
            }
            for offer in state.offers
            if not offer.buyer_failed
        ],
    }


def decide(state: ItemState, now: datetime) -> Action:
    tau = hours_until(state.deadline_at, now)
    inputs = _inputs(state, tau)

    if state.status == ItemStatus.PENDING_PAYMENT:
        if state.checkout is None:
            return Hold(reason="pending payment has no checkout snapshot", inputs=inputs)
        if now >= state.checkout.window_ends_at:
            return PaymentTimeout(
                reason="payment window ended",
                inputs=inputs,
                checkout_id=state.checkout.id,
            )
        return Hold(reason="buyer payment window is still open", inputs=inputs)

    if state.status not in (ItemStatus.LIVE, ItemStatus.ESCALATED):
        return Hold(reason=f"item status {state.status} is not actionable", inputs=inputs)

    if tau <= 0:
        if state.instant_ok and state.instant_preauthorized:
            return RouteInstant(
                reason="deadline passed, using preauthorized instant exit",
                inputs=inputs,
                amount_cents=state.instant_quote_cents,
            )
        return Expire(reason="deadline passed without an executable exit", inputs=inputs)

    target = optimal_price(state, tau)
    standing = tuple(offer for offer in state.offers if not offer.buyer_failed)
    best = max(
        standing,
        key=lambda offer: accept_expected_value_cents(state, offer, tau),
        default=None,
    )
    continuation = target.expected_value_cents

    if best is not None and best.amount_cents >= state.floor_cents:
        accept_value = accept_expected_value_cents(state, best, tau)
        if accept_value >= continuation:
            inputs["accept_expected_value_cents"] = round(accept_value, 2)
            inputs["continue_expected_value_cents"] = round(continuation, 2)
            return Accept(
                reason="offer expected value meets or exceeds continuing value",
                inputs=inputs,
                offer_id=best.id,
                buyer_id=best.buyer_id,
                amount_cents=best.amount_cents,
            )

    unanswered = next((offer for offer in standing if not offer.answered), None)
    if unanswered is not None:
        price = counter_price_cents(state, unanswered, continuation)
        inputs["continue_expected_value_cents"] = round(continuation, 2)
        return Counter(
            reason="offer is worth less than continuing, countering at the executable bound",
            inputs=inputs,
            offer_id=unanswered.id,
            buyer_id=unanswered.buyer_id,
            price_cents=price,
        )

    if (
        tau <= escalation_hours(state)
        and state.status == ItemStatus.LIVE
        and (best is None or best.amount_cents < state.floor_cents)
    ):
        return Escalate(
            reason="deadline is near and no executable offer meets the floor",
            inputs=inputs,
            best_offer_cents=best.amount_cents if best else None,
        )

    if should_reprice(state, target.price_cents, now):
        broadcast_price = max(state.floor_cents, round(target.price_cents * 0.97 / 100) * 100)
        return Reprice(
            reason="optimal price cleared the reprice threshold and cooldown",
            inputs=inputs,
            price_cents=target.price_cents,
            broadcast_price_cents=broadcast_price,
            buyer_ids=state.interested_buyer_ids,
        )

    return Hold(reason="current price remains optimal within hysteresis", inputs=inputs)
