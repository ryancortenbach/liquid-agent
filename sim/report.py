from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

from sim.policies import PolicyName


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(rows: list[dict[str, str]]) -> dict[int, dict[str, dict[str, float]]]:
    grouped: defaultdict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["deadline_hours"]), row["policy"])].append(row)

    summary: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    for (deadline, policy), values in grouped.items():
        summary[deadline][policy] = {
            "mean_net": sum(int(row["net_cents"]) for row in values) / len(values) / 100,
            "sold_rate": sum(row["sold"] == "True" for row in values) / len(values),
            "market_sold_rate": sum(row["exit_kind"] == "market" for row in values) / len(values),
            "interruptions": sum(int(row["seller_interruptions"]) for row in values),
            "violations": sum(int(row["invariant_violations"]) for row in values),
        }
    return dict(summary)


def write_markdown(
    summary: dict[int, dict[str, dict[str, float]]], run_count: int, output: Path
) -> None:
    columns = list(PolicyName)
    lines = [
        "# Evaluation results",
        "",
        f"Seeded simulation with {run_count:,} policy runs.",
        "",
        "| Deadline | "
        + " | ".join(policy.value for policy in columns)
        + " | Agent market sale | Agent exit | Violations |",
        "|---:|" + "---:|" * (len(columns) + 3),
    ]
    for deadline in sorted(summary):
        data = summary[deadline]
        amounts = [f"${data[policy.value]['mean_net']:.0f}" for policy in columns]
        sold = data[PolicyName.AGENT.value]["sold_rate"]
        market_sold = data[PolicyName.AGENT.value]["market_sold_rate"]
        violations = int(data[PolicyName.AGENT.value]["violations"])
        lines.append(
            f"| {deadline}h | "
            + " | ".join(amounts)
            + f" | {market_sold:.0%} | {sold:.0%} | {violations} |"
        )
    lines.extend(
        [
            "",
            "The oracle sees every future executable buyer and represents an upper bound. "
            "Agent exit rate includes the modeled instant exit at the deadline. Agent market sale "
            "rate excludes it. Baselines report zero for unsold inventory. This first harness "
            "models prices, Poisson arrivals, willingness to pay, offers, close reliability, "
            "ghosting, and fees. Response latency and delayed settlement are not modeled yet.",
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def write_chart(summary: dict[int, dict[str, dict[str, float]]], output: Path) -> None:
    deadlines = sorted(summary)
    policies = list(PolicyName)
    width = 0.16
    figure, axis = plt.subplots(figsize=(10, 5.5))
    for index, policy in enumerate(policies):
        offset = (index - (len(policies) - 1) / 2) * width
        axis.bar(
            [position + offset for position in range(len(deadlines))],
            [summary[deadline][policy.value]["mean_net"] for deadline in deadlines],
            width=width,
            label=policy.value.replace("_", " "),
        )
    axis.set_xticks(range(len(deadlines)), [f"{deadline}h" for deadline in deadlines])
    axis.set_ylabel("Mean net proceeds, USD")
    axis.set_title("Liquid policy evaluation")
    axis.legend(ncols=3, frameon=False)
    axis.spines[["top", "right"]].set_visible(False)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Liquid simulation results")
    parser.add_argument("--input", type=Path, default=Path("docs/eval/results.csv"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/eval/results.md"))
    parser.add_argument("--chart", type=Path, default=Path("docs/eval/results.png"))
    args = parser.parse_args()
    rows = read_rows(args.input)
    summary = summarize(rows)
    write_markdown(summary, len(rows), args.markdown)
    write_chart(summary, args.chart)
    print(f"wrote {args.markdown} and {args.chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
