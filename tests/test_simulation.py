from __future__ import annotations

from sim.policies import PolicyName
from sim.run import run_one
from sim.world import ARCHETYPES, generate_market


def test_market_generation_is_seeded() -> None:
    first = generate_market(ARCHETYPES[0], 72, seed=42)
    second = generate_market(ARCHETYPES[0], 72, seed=42)
    assert first == second


def test_agent_never_reports_an_invariant_violation() -> None:
    for archetype in ARCHETYPES:
        for seed in range(10):
            result = run_one(PolicyName.AGENT, archetype, 24, seed)
            assert result.invariant_violations == 0
            assert result.net_cents >= 0


def test_oracle_is_at_least_the_instant_exit() -> None:
    archetype = ARCHETYPES[0]
    for seed in range(10):
        result = run_one(PolicyName.ORACLE, archetype, 12, seed)
        assert result.net_cents >= archetype.instant_cents


def test_agent_never_beats_same_market_oracle() -> None:
    for archetype in ARCHETYPES:
        for deadline in (12, 72):
            for seed in range(10):
                agent = run_one(PolicyName.AGENT, archetype, deadline, seed)
                oracle = run_one(PolicyName.ORACLE, archetype, deadline, seed)
                assert agent.net_cents <= oracle.net_cents
