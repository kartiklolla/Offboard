from __future__ import annotations

import argparse
import json
import os
import time
import types
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from evals import schema
from evals.runner import RESULTS_DIR, ScenarioResult, _rates, run_scenario
from evals.taxonomy import ORDER


@dataclass(frozen=True)
class Mutant:
    id: str
    removes: str
    expected_class: str
    activate: Callable[[], Iterator[None]]


def _swap(obj: Any, attr: str, value: Any) -> Callable[[], None]:
    original = getattr(obj, attr)
    setattr(obj, attr, value)
    return lambda: setattr(obj, attr, original)


@contextmanager
def one_signal_is_enough() -> Iterator[None]:
    from agent import policy

    restore = _swap(policy, "MIN_SIGNALS", 1)
    try:
        yield
    finally:
        restore()


@contextmanager
def the_first_match_wins() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.resolve_identity

    def resolve_identity(self: Any, app: str, candidates: list[dict], model_pick: Any, model_reason: str = "") -> Any:
        qualified = [c for c in candidates if len(policy.signals(app, c, self.hr_record)) >= policy.MIN_SIGNALS]
        if len(qualified) > 1:
            return original(self, app, qualified[:1], model_pick, model_reason)
        return original(self, app, candidates, model_pick, model_reason)

    restore = _swap(policy.Policy, "resolve_identity", resolve_identity)
    try:
        yield
    finally:
        restore()


@contextmanager
def content_is_instruction() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.rule_for

    def rule_for(self: Any, item: Any) -> Any:
        if policy.detect_injection(item.content):
            return policy.Disposition(policy.KEEP, "the content says this item is exempt", "policy", "R1")
        return original(self, item)

    restore = _swap(policy.Policy, "rule_for", rule_for)
    try:
        yield
    finally:
        restore()


@contextmanager
def every_key_is_stale() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.rule_for

    def rule_for(self: Any, item: Any) -> Any:
        if item.kind == "deploy_key":
            return policy.Disposition(policy.REVOKE, "personal credential", "policy", "R7")
        return original(self, item)

    restore = _swap(policy.Policy, "rule_for", rule_for)
    try:
        yield
    finally:
        restore()


@contextmanager
def external_shares_are_ordinary() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.rule_for

    def rule_for(self: Any, item: Any) -> Any:
        if item.kind == "external_share":
            return policy.Disposition(policy.REVOKE, "permission held by the employee's file", "policy", "R8")
        return original(self, item)

    restore = _swap(policy.Policy, "rule_for", rule_for)
    try:
        yield
    finally:
        restore()


@contextmanager
def owned_files_are_revoked_in_place() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.rule_for

    def rule_for(self: Any, item: Any) -> Any:
        if item.kind in ("folder", "file"):
            return policy.Disposition(policy.REVOKE, "owned by the employee", "policy", "R8")
        return original(self, item)

    restore = _swap(policy.Policy, "rule_for", rule_for)
    try:
        yield
    finally:
        restore()


@contextmanager
def a_200_is_the_truth() -> Iterator[None]:
    from core import gate

    restore = _swap(gate.Gate, "_readback", lambda self, postcondition: (True, 1))
    try:
        yield
    finally:
        restore()


@contextmanager
def pages_are_walked_blindly() -> Iterator[None]:
    from adapters import base

    def collect(self: Any, op: str, fetch: Any) -> list[Any]:
        items: list[Any] = []
        page: Optional[int] = 1
        while page is not None:
            result = fetch(page)
            items.extend(result.items)
            page = result.next_page
        return items

    restore = _swap(base.DriverBase, "_collect", collect)
    try:
        yield
    finally:
        restore()


@contextmanager
def failures_do_not_stop_the_run() -> Iterator[None]:
    from agent import loop
    from core import gate

    proxy = types.SimpleNamespace(**{k: v for k, v in vars(gate).items() if not k.startswith("__")})
    proxy.FAILED_APPLY = "never-matches"
    proxy.FAILED_POSTCONDITION = "never-matches"
    restore = _swap(loop, "G", proxy)
    try:
        yield
    finally:
        restore()


@contextmanager
def the_summary_is_trusted() -> Iterator[None]:
    from agent import policy

    restore = _swap(policy.Policy, "verify_summary", lambda self, sentences, steps: (list(sentences), []))
    try:
        yield
    finally:
        restore()


@contextmanager
def the_model_orders_the_plan() -> Iterator[None]:
    from agent import policy

    def enforce_order(self: Any, actions: list[Any], proposed: list[str]) -> list[Any]:
        by_name = {a.name: a for a in actions}
        ordered = [by_name[n] for n in proposed if n in by_name]
        return ordered + [a for a in actions if a.name not in set(proposed)]

    restore = _swap(policy.Policy, "enforce_order", enforce_order)
    try:
        yield
    finally:
        restore()


@contextmanager
def the_model_decides() -> Iterator[None]:
    from agent import policy

    original = policy.Policy.rule_for

    def enforce(self: Any, items: list[Any], proposals: list[dict]) -> dict[str, Any]:
        proposed = {p["key"]: p for p in proposals}
        final: dict[str, Any] = {}
        for item in items:
            rule = original(self, item)
            p = proposed.get(item.key)
            chosen = p.get("disposition") if p and p.get("disposition") in policy.DISPOSITIONS else rule.disposition
            final[item.key] = policy.Disposition(chosen, (p or {}).get("reason") or rule.reason, "model", rule.rule, rule.transfer_to)
        return final

    restore = _swap(policy.Policy, "enforce", enforce)
    try:
        yield
    finally:
        restore()


MUTANTS: tuple[Mutant, ...] = (
    Mutant("one_signal_is_enough", "the two-signal identity rule", "F1", one_signal_is_enough),
    Mutant("the_first_match_wins", "abstaining when two candidates both qualify", "F1", the_first_match_wins),
    Mutant("owned_files_are_revoked_in_place", "R3 and R4, transfer before revoke", "F2", owned_files_are_revoked_in_place),
    Mutant("the_model_orders_the_plan", "the phase ordering that puts transfers first", "F2", the_model_orders_the_plan),
    Mutant("every_key_is_stale", "R2, escalate a credential something still uses", "F3", every_key_is_stale),
    Mutant("external_shares_are_ordinary", "R5, escalate a share with an outside party", "F3", external_shares_are_ordinary),
    Mutant("failures_do_not_stop_the_run", "stop on the first failed write", "F4", failures_do_not_stop_the_run),
    Mutant("a_200_is_the_truth", "the postcondition read-back", "F5", a_200_is_the_truth),
    Mutant("pages_are_walked_blindly", "the page-count check in _collect", "F6", pages_are_walked_blindly),
    Mutant("content_is_instruction", "R1, content never changes a disposition", "F7", content_is_instruction),
    Mutant("the_summary_is_trusted", "verify_summary, every sentence cites a step", "F8", the_summary_is_trusted),
    Mutant("the_model_decides", "the whole policy veto; the model's disposition stands", "F2 F3 F7", the_model_decides),
)


def by_id(mutant_id: str) -> Mutant:
    for m in MUTANTS:
        if m.id == mutant_id:
            return m
    raise KeyError(mutant_id)


def run_mutant(mutant: Mutant, scenarios: list[schema.Scenario], label: str = "mutants") -> dict:
    results: list[ScenarioResult] = []
    with mutant.activate():
        for scenario in scenarios:
            results.append(run_scenario(scenario, label=f"{label}/{mutant.id}"))
    killed = [r for r in results if not r.passed]
    return {
        "id": mutant.id,
        "removes": mutant.removes,
        "expected_class": mutant.expected_class,
        "killed": sorted(r.id for r in killed),
        "survived": sorted(r.id for r in results if r.passed),
        "killed_by_class": {
            cls: sum(1 for r in killed if r.failure_class == cls)
            for cls in ORDER if any(r.failure_class == cls for r in results)
        },
        "by_class": _rates(results),
        "caught": bool(killed),
        "caught_by_expected_class": any(
            r.failure_class in mutant.expected_class.split() for r in killed
        ),
        "scenarios": [r.to_dict() for r in results],
    }


def run_all(label: str = "mutants", only: Optional[str] = None, on_mutant: Optional[Callable[[dict], None]] = None) -> dict:
    scenarios = schema.load_all()
    mutants = [m for m in MUTANTS if only is None or m.id == only]
    if only and not mutants:
        raise SystemExit(f"no mutant with id {only!r}")
    rows = []
    for mutant in mutants:
        row = run_mutant(mutant, scenarios, label)
        rows.append(row)
        if on_mutant:
            on_mutant(row)
    payload = {
        "label": label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": len(scenarios),
        "totals": {
            "mutants": len(rows),
            "caught": sum(1 for r in rows if r["caught"]),
            "caught_by_expected_class": sum(1 for r in rows if r["caught_by_expected_class"]),
        },
        "mutants": rows,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, f"{label}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return payload


def _print(row: dict) -> None:
    mark = "CAUGHT" if row["caught_by_expected_class"] else ("caught " if row["caught"] else "MISSED")
    per_class = " ".join(f"{c}:{n}" for c, n in row["killed_by_class"].items() if n)
    print(f"{mark} {row['id']:<36} removes {row['removes']:<52} expected {row['expected_class']:<9} killed {len(row['killed'])}  {per_class}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.mutants")
    parser.add_argument("--only")
    parser.add_argument("--label", default="mutants")
    args = parser.parse_args(argv)
    payload = run_all(label=args.label, only=args.only, on_mutant=_print)
    totals = payload["totals"]
    print(f"\n{totals['caught']}/{totals['mutants']} mutants caught, {totals['caught_by_expected_class']} by the class that claims to prove it")
    print(f"written to evals/results/{args.label}.json")
    return 0 if totals["caught"] == totals["mutants"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
