from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.engine.actions import Accept, Counter
from app.engine.demand import optimal_price
from app.engine.guard import InvariantViolation, check
from app.engine.policy import decide
from app.engine.state import ChannelState, ItemState, StandingOffer
from app.market.fees import net_proceeds_cents
from app.models import ItemStatus
from sim.policies import PolicyName, baseline_price_cents
from sim.world import ARCHETYPES, Archetype, BuyerEvent, generate_market


@dataclass(frozen=True, slots=True)
class SimulationResult:
    policy: PolicyName
    archetype: str
    deadline_hours: int
    seed: int
    net_cents: int
    sold: bool
    sale_hour: float | None
    exit_kind: str
    seller_interruptions: int
    invariant_violations: int


def channels_for(
    archetype: Archetype,
    elapsed_hours: float,
    inquiries: dict[str, int],
) -> tuple[ChannelState, ...]:
    return (
        ChannelState(
            "local",
            prior_alpha=archetype.local_arrivals_per_day,
            prior_beta_hours=24,
            elapsed_hours=elapsed_hours,
            inquiries=inquiries["local"],
            views=round(elapsed_hours * archetype.local_arrivals_per_day / 24 * 20),
        ),
        ChannelState(
            "ebay",
            prior_alpha=archetype.ebay_arrivals_per_day,
            prior_beta_hours=24,
            elapsed_hours=elapsed_hours,
            inquiries=inquiries["ebay"],
            views=round(elapsed_hours * archetype.ebay_arrivals_per_day / 24 * 20),
        ),
    )


def agent_state(
    archetype: Archetype,
    deadline_hours: int,
    elapsed_hours: float,
    current_price: int,
    inquiries: dict[str, int],
    offer: StandingOffer | None = None,
) -> tuple[ItemState, datetime]:
    start = datetime(2026, 9, 13, 16, tzinfo=UTC)
    now = start + timedelta(hours=elapsed_hours)
    state = ItemState(
        item_id="sim-item",
        status=ItemStatus.LIVE,
        deadline_at=start + timedelta(hours=deadline_hours),
        original_horizon_hours=deadline_hours,
        floor_cents=archetype.floor_cents,
        market_value_cents=archetype.market_cents,
        sigma_cents=archetype.sigma_cents,
        instant_quote_cents=archetype.instant_cents,
        instant_ok=True,
        instant_preauthorized=True,
        current_price_cents=current_price,
        channels=channels_for(archetype, elapsed_hours, inquiries),
        offers=(offer,) if offer else (),
    )
    return state, now


def oracle_result(
    archetype: Archetype,
    deadline_hours: int,
    seed: int,
    events: list[BuyerEvent],
) -> SimulationResult:
    executable = [
        (
            net_proceeds_cents(event.channel, event.willingness_cents),
            event.at_hours,
        )
        for event in events
        if not event.ghost and event.pays and event.willingness_cents >= archetype.floor_cents
    ]
    best_net, sale_hour = max(executable, default=(0, float(deadline_hours)))
    exit_kind = "market"
    if best_net < archetype.instant_cents:
        best_net, sale_hour = archetype.instant_cents, float(deadline_hours)
        exit_kind = "instant"
    return SimulationResult(
        policy=PolicyName.ORACLE,
        archetype=archetype.name,
        deadline_hours=deadline_hours,
        seed=seed,
        net_cents=best_net,
        sold=True,
        sale_hour=sale_hour,
        exit_kind=exit_kind,
        seller_interruptions=0,
        invariant_violations=0,
    )


def run_one(
    policy: PolicyName,
    archetype: Archetype,
    deadline_hours: int,
    seed: int,
) -> SimulationResult:
    events = generate_market(archetype, deadline_hours, seed)
    if policy == PolicyName.ORACLE:
        return oracle_result(archetype, deadline_hours, seed, events)

    inquiries = {"local": 0, "ebay": 0}
    current_price = archetype.market_cents
    if policy == PolicyName.AGENT:
        state, _ = agent_state(archetype, deadline_hours, 0, current_price, inquiries)
        current_price = optimal_price(state, deadline_hours).price_cents
    interruptions = 0
    violations = 0

    for index, event in enumerate(events):
        if policy == PolicyName.AGENT:
            state, now = agent_state(
                archetype,
                deadline_hours,
                event.at_hours,
                current_price,
                inquiries,
            )
            target = optimal_price(state, max(0, deadline_hours - event.at_hours)).price_cents
            current_price = max(archetype.floor_cents, min(current_price, target))
        else:
            current_price = baseline_price_cents(policy, archetype, event.at_hours, deadline_hours)

        if current_price <= event.willingness_cents * 1.15:
            inquiries[event.channel] += 1

        if event.willingness_cents >= current_price and not event.ghost and event.pays:
            return SimulationResult(
                policy=policy,
                archetype=archetype.name,
                deadline_hours=deadline_hours,
                seed=seed,
                net_cents=net_proceeds_cents(event.channel, current_price),
                sold=True,
                sale_hour=event.at_hours,
                exit_kind="market",
                seller_interruptions=interruptions,
                invariant_violations=violations,
            )

        if policy == PolicyName.AGENT and event.offer_cents > 0 and not event.ghost:
            offer = StandingOffer(
                id=f"offer-{index}",
                buyer_id=f"buyer-{index}",
                amount_cents=event.offer_cents,
                channel=event.channel,
                pay_reliability=0.85 if event.channel == "local" else 0.97,
                settlement_hours=0.1 if event.channel == "local" else 96,
            )
            offer_state, now = agent_state(
                archetype,
                deadline_hours,
                event.at_hours,
                current_price,
                inquiries,
                offer,
            )
            action = decide(offer_state, now)
            try:
                check(action, offer_state, now)
            except InvariantViolation:
                violations += 1
                continue
            agreed_price = None
            if isinstance(action, Accept):
                agreed_price = action.amount_cents
            elif isinstance(action, Counter) and action.price_cents <= event.willingness_cents:
                agreed_price = action.price_cents
            if agreed_price is not None and event.pays:
                return SimulationResult(
                    policy=policy,
                    archetype=archetype.name,
                    deadline_hours=deadline_hours,
                    seed=seed,
                    net_cents=net_proceeds_cents(event.channel, agreed_price),
                    sold=True,
                    sale_hour=event.at_hours,
                    exit_kind="market",
                    seller_interruptions=interruptions,
                    invariant_violations=violations,
                )

    if policy == PolicyName.AGENT:
        interruptions = 1
        return SimulationResult(
            policy=policy,
            archetype=archetype.name,
            deadline_hours=deadline_hours,
            seed=seed,
            net_cents=archetype.instant_cents,
            sold=True,
            sale_hour=float(deadline_hours),
            exit_kind="instant",
            seller_interruptions=interruptions,
            invariant_violations=violations,
        )
    return SimulationResult(
        policy=policy,
        archetype=archetype.name,
        deadline_hours=deadline_hours,
        seed=seed,
        net_cents=0,
        sold=False,
        sale_hour=None,
        exit_kind="unsold",
        seller_interruptions=interruptions,
        invariant_violations=violations,
    )


def run_grid(seeds: int) -> list[SimulationResult]:
    return [
        run_one(policy, archetype, deadline, seed)
        for deadline in (12, 24, 72, 168)
        for archetype in ARCHETYPES
        for seed in range(seeds)
        for policy in PolicyName
    ]


def write_results(results: list[SimulationResult], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(SimulationResult.__annotations__),
            lineterminator="\n",
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    field: getattr(result, field).value
                    if isinstance(getattr(result, field), PolicyName)
                    else getattr(result, field)
                    for field in SimulationResult.__annotations__
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Liquid market simulation grid")
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("docs/eval/results.csv"))
    args = parser.parse_args()
    results = run_grid(args.seeds)
    write_results(results, args.output)
    print(f"wrote {len(results)} policy runs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
