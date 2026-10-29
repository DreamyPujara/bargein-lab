#!/usr/bin/env python3
"""Offline interruption-testing sandbox for synthetic voice-agent events.

This module is intentionally small, deterministic, and standard-library only.
It measures how long a synthetic voice agent keeps speaking after a synthetic
user interruption, then optionally compares a candidate event stream against a
baseline with regression gates.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

VALID_TYPES = {"agent_start", "agent_stop", "user_start", "user_stop"}


@dataclass(frozen=True)
class Interruption:
    user_start_ms: int
    agent_stop_ms: int | None

    @property
    def delay_ms(self) -> int | None:
        if self.agent_stop_ms is None:
            return None
        return self.agent_stop_ms - self.user_start_ms


def _is_plain_int(value: Any) -> bool:
    """Return True for JSON integer timestamps, but not booleans.

    In Python, bool is a subclass of int. JSON `true`/`false` should not be
    accepted as millisecond timestamps because that is surprising for CLI users
    and makes input mistakes look valid.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def load_events(path: str | Path) -> List[Dict[str, Any]]:
    """Load and validate an event stream from JSON.

    Accepted formats:
    - [{"time_ms": 0, "type": "agent_start"}, ...]
    - {"events": [{"time_ms": 0, "type": "agent_start"}, ...]}
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "events" in data:
        events = data["events"]
    else:
        events = data

    if not isinstance(events, list):
        raise ValueError("event stream must be a JSON list or an object with an 'events' list")

    validated: List[Dict[str, Any]] = []
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"event {i} must be an object")
        if "time_ms" not in event or "type" not in event:
            raise ValueError(f"event {i} must contain time_ms and type")
        time_ms = event["time_ms"]
        kind = event["type"]
        if not _is_plain_int(time_ms) or time_ms < 0:
            raise ValueError(f"event {i} time_ms must be a non-negative integer")
        if kind not in VALID_TYPES:
            raise ValueError(f"event {i} type must be one of {sorted(VALID_TYPES)}")
        validated.append({"time_ms": time_ms, "type": kind})

    return sorted(validated, key=lambda e: (e["time_ms"], e["type"]))


def find_interruptions(events: Sequence[Dict[str, Any]]) -> List[Interruption]:
    """Find user_start events that occur while the synthetic agent is speaking.

    A cancellation delay is measured from user_start to the next agent_stop.
    Multiple user_start events before the same agent_stop are each counted,
    because each represents a separate synthetic interruption attempt.
    """
    agent_speaking = False
    pending_user_starts: List[int] = []
    interruptions: List[Interruption] = []

    for event in sorted(events, key=lambda e: (e["time_ms"], e["type"])):
        t = int(event["time_ms"])
        kind = event["type"]

        if kind == "agent_start":
            agent_speaking = True
        elif kind == "user_start":
            if agent_speaking:
                pending_user_starts.append(t)
        elif kind == "agent_stop":
            if agent_speaking:
                for start in pending_user_starts:
                    interruptions.append(Interruption(start, t))
                pending_user_starts = []
            agent_speaking = False
        elif kind == "user_stop":
            pass

    for start in pending_user_starts:
        interruptions.append(Interruption(start, None))

    return interruptions


def percentile_nearest_rank(values: Sequence[int], percentile: float) -> int | None:
    """Return nearest-rank percentile for deterministic small-sample reporting."""
    if not values:
        return None
    if percentile <= 0:
        return min(values)
    if percentile >= 100:
        return max(values)
    ordered = sorted(values)
    rank = math.ceil((percentile / 100.0) * len(ordered))
    return ordered[rank - 1]


def summarize(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    interruptions = find_interruptions(events)
    delays = [i.delay_ms for i in interruptions if i.delay_ms is not None]
    delays_int = [int(d) for d in delays]
    missed = sum(1 for i in interruptions if i.delay_ms is None)

    summary: Dict[str, Any] = {
        "interruptions": len(interruptions),
        "completed_cancellations": len(delays_int),
        "missed_cancellations": missed,
        "delays_ms": delays_int,
        "avg_delay_ms": None,
        "p95_delay_ms": None,
        "max_delay_ms": None,
    }
    if delays_int:
        summary["avg_delay_ms"] = round(sum(delays_int) / len(delays_int), 2)
        summary["p95_delay_ms"] = percentile_nearest_rank(delays_int, 95)
        summary["max_delay_ms"] = max(delays_int)
    return summary


def compare_summaries(
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    max_p95_ms: int | None,
    max_regression_ms: int | None,
    allow_more_missed: bool,
) -> Tuple[bool, List[str]]:
    failures: List[str] = []

    candidate_p95 = candidate.get("p95_delay_ms")
    baseline_p95 = baseline.get("p95_delay_ms")

    if max_p95_ms is not None:
        if candidate_p95 is None:
            failures.append("candidate has no completed cancellations, so p95 cannot be evaluated")
        elif candidate_p95 > max_p95_ms:
            failures.append(f"candidate p95_delay_ms {candidate_p95} > gate {max_p95_ms}")

    if max_regression_ms is not None:
        if candidate_p95 is None or baseline_p95 is None:
            failures.append("p95 regression cannot be evaluated without completed cancellations in both streams")
        elif candidate_p95 - baseline_p95 > max_regression_ms:
            failures.append(
                f"candidate p95_delay_ms regressed by {candidate_p95 - baseline_p95} ms > gate {max_regression_ms}"
            )

    if not allow_more_missed and candidate.get("missed_cancellations", 0) > baseline.get("missed_cancellations", 0):
        failures.append(
            "candidate missed_cancellations "
            f"{candidate.get('missed_cancellations', 0)} > baseline {baseline.get('missed_cancellations', 0)}"
        )

    return not failures, failures


def print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_measure(args: argparse.Namespace) -> int:
    try:
        events = load_events(args.events)
        print_json(summarize(events))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        baseline_events = load_events(args.baseline)
        candidate_events = load_events(args.candidate)
        baseline = summarize(baseline_events)
        candidate = summarize(candidate_events)
        passed, failures = compare_summaries(
            baseline,
            candidate,
            max_p95_ms=args.max_p95_ms,
            max_regression_ms=args.max_regression_ms,
            allow_more_missed=args.allow_more_missed,
        )
        print_json({"passed": passed, "failures": failures, "baseline": baseline, "candidate": candidate})
        return 0 if passed else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def demo_events() -> Dict[str, Any]:
    return {
        "baseline": [
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 900, "type": "user_start"},
            {"time_ms": 1110, "type": "agent_stop"},
            {"time_ms": 1400, "type": "agent_start"},
            {"time_ms": 1800, "type": "user_start"},
            {"time_ms": 2050, "type": "agent_stop"},
        ],
        "candidate": [
            {"time_ms": 0, "type": "agent_start"},
            {"time_ms": 900, "type": "user_start"},
            {"time_ms": 1020, "type": "agent_stop"},
            {"time_ms": 1400, "type": "agent_start"},
            {"time_ms": 1800, "type": "user_start"},
            {"time_ms": 1940, "type": "agent_stop"},
        ],
    }


def cmd_demo(_: argparse.Namespace) -> int:
    data = demo_events()
    baseline = summarize(data["baseline"])
    candidate = summarize(data["candidate"])
    passed, failures = compare_summaries(baseline, candidate, max_p95_ms=180, max_regression_ms=0, allow_more_missed=False)
    print_json({"synthetic_events": data, "passed": passed, "failures": failures, "baseline": baseline, "candidate": candidate})
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure synthetic voice-agent cancellation delay after user interruptions."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    measure = sub.add_parser("measure", help="summarize one event stream")
    measure.add_argument("events", help="JSON event stream path")
    measure.set_defaults(func=cmd_measure)

    compare = sub.add_parser("compare", help="compare baseline and candidate event streams with gates")
    compare.add_argument("baseline", help="baseline JSON event stream path")
    compare.add_argument("candidate", help="candidate JSON event stream path")
    compare.add_argument("--max-p95-ms", type=int, default=250, help="maximum allowed candidate p95 delay")
    compare.add_argument(
        "--max-regression-ms",
        type=int,
        default=25,
        help="maximum allowed candidate p95 regression versus baseline",
    )
    compare.add_argument(
        "--allow-more-missed",
        action="store_true",
        help="do not fail if candidate has more missed cancellations than baseline",
    )
    compare.set_defaults(func=cmd_compare)

    demo = sub.add_parser("demo", help="run a built-in synthetic comparison")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
