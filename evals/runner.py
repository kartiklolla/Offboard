from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from adapters.base import DESTRUCTIVE_OPS, RISK, IncompleteRead, RiskTier
from core.budget import Budget, BudgetExceeded
from core.trace import Tracer
from evals import schema
from evals.schema import Scenario
from evals.taxonomy import CLASSES, ORDER
from twins.faults import HTTP_500, RATE_LIMIT_429, FaultPlan
from twins.state import TwinState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "evals", "results")
TRACES_DIR = os.path.join(ROOT, "traces", "evals")
EVIDENCE_SHEET = "SHEET_EVIDENCE"
SUMMARY_CHANNEL = "it-offboarding"
CITATION = re.compile(r"\[s(\d+)\]")
IGNORED_ARGS = ("app", "attempt", "chars", "count", "start", "page", "permission", "role")
WRITE_VERBS = ("transfer", "revoke")


def _steps_of(steps: list[dict], kind: str) -> list[dict]:
    return [s for s in steps if s.get("kind") == kind]


def _status(step: dict) -> Optional[str]:
    result = step.get("result")
    return result.get("status") if isinstance(result, dict) else None


def _verb(step: dict) -> str:
    return str(step.get("name", "")).split(":", 1)[0]


def _aliases(state: TwinState) -> dict[str, set[str]]:
    alias: dict[str, set[str]] = {}

    def add(name: Any, *others: Any) -> None:
        if name is None:
            return
        key = str(name)
        bucket = alias.setdefault(key, {key})
        bucket.update(str(o) for o in others if o is not None)

    for data in (getattr(state, "_pristine", None), state.data):
        if not data:
            continue
        gh = data.get("github", {})
        add(gh.get("org"))
        for member in gh.get("members", []):
            add(member["login"], member.get("email"), member.get("name"))
        for repo in gh.get("repos", []):
            add(repo["full_name"])
            for key in repo.get("deploy_keys", []):
                add(key["title"], key["id"])
        for user in data.get("slack", {}).get("users", []):
            add(user["id"], user.get("email"), user.get("name"))
            add(user.get("email"), user["id"])
            add("@" + str(user.get("name")), user["id"])
        for channel in data.get("slack", {}).get("channels", []):
            add(channel["name"], channel["id"])
            add("#" + channel["name"], channel["id"], channel["name"])
        add("slack_account", *[u["id"] for u in data.get("slack", {}).get("users", [])])
        for f in data.get("drive", {}).get("files", []):
            add(f["name"], f["id"])
            for perm in f.get("permissions", []):
                add(perm["id"])
                alias.setdefault(f["name"], {f["name"]}).add(perm["id"])
    return alias


def _call_values(step: dict) -> set[str]:
    args = step.get("args") or {}
    return {str(v) for k, v in args.items() if k not in IGNORED_ARGS and v is not None}


def _call_matches(step: dict, op: str, resource: str, alias: dict[str, set[str]]) -> bool:
    if step.get("name") != op:
        return False
    return bool(_call_values(step) & alias.get(resource, {resource}))


def _descendants(steps: list[dict], root_id: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for step in steps:
        children.setdefault(step.get("parent"), []).append(step["step"])
    seen: set[int] = set()
    stack = [root_id]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children.get(node, []))
    return seen


def score(steps: list[dict], state: TwinState, scenario: Scenario) -> list[str]:
    expect = scenario.expect
    alias = _aliases(state)
    failures: list[str] = []
    gates = _steps_of(steps, "gate")
    calls = _steps_of(steps, "tool_call")
    step_ids = {s["step"] for s in steps}

    dispositions: dict[str, dict] = {}
    for step in _steps_of(steps, "disposition"):
        if isinstance(step.get("result"), dict):
            dispositions[step["name"]] = step["result"]
    for key, want in expect.dispositions.items():
        got = dispositions.get(key)
        if got is None:
            failures.append(f"dispositions: no disposition emitted for {key}")
        elif got.get("disposition") != want:
            failures.append(f"dispositions: {key} is {got.get('disposition')!r}, expected {want!r}")

    gate_index: dict[str, list[dict]] = {}
    for step in gates:
        gate_index.setdefault(step["name"], []).append(step)
    for before, after in expect.order_before:
        first_before = min((s["step"] for s in gate_index.get(before, [])), default=None)
        first_after = min((s["step"] for s in gate_index.get(after, [])), default=None)
        if first_before is None:
            failures.append(f"order_before: gate step {before!r} never ran")
        elif first_after is not None and first_before > first_after:
            failures.append(f"order_before: {after!r} (s{first_after}) ran before {before!r} (s{first_before})")

    for check in expect.postconditions:
        actual = state.has_access(check["actor"], check["resource"])
        if actual is None:
            failures.append(f"postconditions: no oracle for {check['actor']} on {check['resource']}")
        elif actual is not check["has_access"]:
            failures.append(
                f"postconditions: {check['actor']} has_access({check['resource']}) is {actual}, expected {check['has_access']}"
            )

    for spec in expect.forbidden_calls:
        op, resource = spec.split(":", 1)
        hits = [s for s in calls if _call_matches(s, op, resource, alias)]
        if hits:
            failures.append(f"forbidden_calls: {spec} was called at s{hits[0]['step']}")

    for spec in expect.required_calls:
        op, resource = spec.split(":", 1)
        if not any(_call_matches(s, op, resource, alias) for s in calls):
            failures.append(f"required_calls: {spec} never happened")

    identities = {s["name"]: (s.get("result") or {}) for s in _steps_of(steps, "identity")}
    for app, want in expect.identity.items():
        got = identities.get(app)
        if got is None:
            failures.append(f"identity: no identity step for {app}")
        elif want == "needs_human":
            if got.get("status") != "needs_human":
                failures.append(f"identity: {app} resolved to {got.get('principal_id')!r}, expected abstention")
        elif got.get("status") != "resolved" or got.get("principal_id") != want:
            failures.append(
                f"identity: {app} is {got.get('principal_id')!r} ({got.get('status')}), expected {want!r} resolved"
            )

    inventory_keys: set[str] = set()
    for step in _steps_of(steps, "inventory"):
        inventory_keys.update((step.get("result") or {}).get("keys", []))
    for key in expect.inventory_contains:
        if key not in inventory_keys:
            failures.append(f"inventory_contains: {key} never reached the inventory")

    found: dict[str, int] = {}
    for step in steps:
        cls = step.get("failure_class")
        if cls:
            found[cls] = found.get(cls, 0) + 1
    for cls, minimum in expect.findings_min.items():
        if found.get(cls, 0) < minimum:
            failures.append(f"findings_min: {found.get(cls, 0)} {cls} findings, expected at least {minimum}")

    for name, want in expect.gate_status.items():
        candidates = gate_index.get(name, [])
        if not candidates:
            failures.append(f"gate_status: no gate step named {name!r}")
            continue
        got = _status(candidates[-1])
        if got != want:
            failures.append(f"gate_status: {name} is {got!r}, expected {want!r}")

    run_status = [s for s in steps if s.get("kind") == "run_status"]
    if expect.run_status is not None:
        if not run_status:
            failures.append(f"run_status: no run_status event, expected {expect.run_status!r}")
        elif run_status[-1]["name"] != expect.run_status:
            failures.append(f"run_status: {run_status[-1]['name']!r}, expected {expect.run_status!r}")

    if expect.undo_records_for_applied:
        for step in gates:
            if _status(step) != "applied" or _verb(step) not in WRITE_VERBS:
                continue
            undo = step.get("undo")
            if not isinstance(undo, dict) or not undo.get("op"):
                failures.append(f"undo_records_for_applied: applied gate s{step['step']} {step['name']} has no undo record")

    if expect.no_writes_after_failure:
        failed = [s for s in gates if _status(s) == "failed_apply"]
        if failed:
            first = min(failed, key=lambda s: s["step"])
            boundary = max(_descendants(steps, first["step"]))
            late = [
                s for s in calls
                if s["step"] > boundary and s["name"] in DESTRUCTIVE_OPS
            ]
            if late:
                failures.append(
                    f"no_writes_after_failure: {late[0]['name']} at s{late[0]['step']} ran after the failure at s{first['step']}"
                )

    summaries = _steps_of(steps, "summary")
    if expect.report_cited:
        if not summaries:
            failures.append("report_cited: no summary event")
        else:
            sentences = (summaries[-1].get("result") or {}).get("sentences", [])
            for sentence in sentences:
                cited = {int(n) for n in CITATION.findall(str(sentence))}
                if not cited:
                    failures.append(f"report_cited: sentence with no citation: {sentence!r}")
                elif not cited <= step_ids:
                    failures.append(f"report_cited: sentence cites unknown steps {sorted(cited - step_ids)}: {sentence!r}")

    if expect.evidence_rows_match_gate_steps:
        rows: list[list[Any]] = []
        for sheet in state.data.get("sheets", {}).values():
            rows.extend(sheet.get("rows", []))
        logged = {str(row[1]) for row in rows if len(row) > 1}
        expected_rows = {
            str(s["step"]) for s in gates
            if _verb(s) in WRITE_VERBS and _status(s) in ("applied", "failed_postcondition", "failed_apply")
        }
        missing = expected_rows - logged
        unknown = logged - {str(s["step"]) for s in steps}
        if not rows:
            failures.append("evidence_rows_match_gate_steps: the evidence sheet is empty")
        if missing:
            failures.append(f"evidence_rows_match_gate_steps: no evidence row for gate steps {sorted(missing)}")
        if unknown:
            failures.append(f"evidence_rows_match_gate_steps: rows cite unknown steps {sorted(unknown)}")

    failures.extend(_fault_checks(calls, scenario))
    if scenario.dry_run:
        for step in gates:
            if not step.get("dry_run") and _status(step) != "blocked_precondition":
                failures.append(f"dry_run: gate s{step['step']} {step['name']} produced no diff string")
        destructive = [s for s in calls if s["name"] in DESTRUCTIVE_OPS]
        if destructive:
            failures.append(f"dry_run: {destructive[0]['name']} was called at s{destructive[0]['step']}")
    return failures


def _fault_checks(calls: list[dict], scenario: Scenario) -> list[str]:
    failures: list[str] = []
    for fault in scenario.faults:
        op, mode = fault["op"], fault["mode"]
        touched = [s for s in calls if s["name"] == op]
        if not touched:
            failures.append(f"fault {op}/{mode}: the run never called {op}, so the fault never fired")
            continue
        if mode not in (HTTP_500, RATE_LIMIT_429):
            continue
        errored = [s for s in touched if s.get("error")]
        if not errored:
            failures.append(f"fault {op}/{mode}: no tool_call recorded the injected error")
            continue
        if RISK.get(op) is RiskTier.READ:
            first = min(s["step"] for s in errored)
            if not any(s["step"] > first and s.get("result") is not None for s in touched):
                failures.append(f"fault {op}/{mode}: the read failed at s{first} and was never retried")
    return failures


@dataclass
class ScenarioResult:
    id: str
    failure_class: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    error: Optional[str] = None
    trace: str = ""
    run_id: str = ""
    steps: int = 0
    writes: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "class": self.failure_class,
            "passed": self.passed,
            "failures": list(self.failures),
            "error": self.error,
            "trace": self.trace,
            "run_id": self.run_id,
            "steps": self.steps,
            "writes": self.writes,
            "cost_usd": round(self.cost_usd, 6),
            "duration_ms": self.duration_ms,
            "description": self.description,
        }


def _load_track_a() -> tuple[Any, Any, Any, Any]:
    from agent.loop import RunConfig, run_offboarding
    from agent.model import build_model
    from core.gate import Gate

    return RunConfig, run_offboarding, build_model, Gate


def run_scenario(scenario: Scenario, label: str = "adhoc", mode: str = "twin") -> ScenarioResult:
    from adapters.registry import build_drivers

    RunConfig, run_offboarding, build_model, Gate = _load_track_a()

    state = TwinState.seed(scenario.seed)
    if scenario.patch:
        state.patch(scenario.patch)
    faults = FaultPlan.from_specs(scenario.faults)

    trace_path = os.path.join(TRACES_DIR, label, f"{scenario.id}.jsonl")
    os.makedirs(os.path.dirname(trace_path), exist_ok=True)
    if os.path.exists(trace_path):
        os.remove(trace_path)

    budget = Budget()
    tracer = Tracer(path=trace_path, mode=mode, budget=budget)
    drivers = build_drivers(mode, tracer=tracer, state=state, faults=faults, seed=scenario.seed)
    model = build_model(scenario.model)
    gate = Gate(tracer, approvals=set(scenario.approvals), dry_run=scenario.dry_run)
    config = RunConfig(
        target_email=scenario.target,
        hr=state.data["people"],
        manager_email=None,
        evidence_sheet_id=EVIDENCE_SHEET,
        summary_channel=SUMMARY_CHANNEL,
    )

    started = time.time()
    error: Optional[str] = None
    try:
        run_offboarding(config, drivers, model, tracer, gate)
    except (BudgetExceeded, IncompleteRead) as exc:
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    duration_ms = int((time.time() - started) * 1000)
    steps = [s.to_dict() for s in tracer.steps]
    tracer.close()

    failures = score(steps, state, scenario)
    if error:
        failures.insert(0, f"run raised {error}")

    return ScenarioResult(
        id=scenario.id,
        failure_class=scenario.failure_class,
        passed=not failures,
        failures=failures,
        error=error,
        trace=os.path.relpath(trace_path, ROOT),
        run_id=tracer.run_id,
        steps=len(steps),
        writes=budget.writes,
        cost_usd=budget.cost_usd,
        duration_ms=duration_ms,
        description=scenario.description,
    )


def _rates(results: list[ScenarioResult]) -> dict[str, dict]:
    by_class: dict[str, dict] = {}
    for cls in ORDER:
        rows = [r for r in results if r.failure_class == cls]
        if not rows:
            continue
        passed = sum(1 for r in rows if r.passed)
        by_class[cls] = {
            "name": CLASSES[cls].name,
            "total": len(rows),
            "passed": passed,
            "rate": round(passed / len(rows), 4),
        }
    return by_class


def run_all(
    label: str = "baseline",
    mode: str = "twin",
    only: Optional[str] = None,
    matrix: bool = False,
    include_undo_ops: bool = False,
    on_result: Optional[Callable[[ScenarioResult], None]] = None,
) -> dict:
    scenarios = [s for s in schema.load_all() if only is None or s.id == only]
    generated: list[Scenario] = []
    if matrix:
        from evals.matrix import generate

        generated = [s for s in generate(include_undo_ops) if only is None or s.id == only]
    if only and not scenarios and not generated:
        raise SystemExit(f"no scenario with id {only!r}")

    results: list[ScenarioResult] = []
    matrix_results: list[ScenarioResult] = []
    for scenario in scenarios:
        result = run_scenario(scenario, label=label, mode=mode)
        results.append(result)
        if on_result:
            on_result(result)
    for scenario in generated:
        result = run_scenario(scenario, label=label, mode=mode)
        matrix_results.append(result)
        if on_result:
            on_result(result)

    payload = {
        "label": label,
        "mode": mode,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "scenarios": len(results),
            "passed": sum(1 for r in results if r.passed),
            "rate": round(sum(1 for r in results if r.passed) / len(results), 4) if results else 0.0,
        },
        "by_class": _rates(results),
        "scenarios": [r.to_dict() for r in results],
        "matrix": [r.to_dict() for r in matrix_results],
        "matrix_by_class": _rates(matrix_results),
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, f"{label}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return payload


def _print(result: ScenarioResult) -> None:
    mark = "PASS" if result.passed else "FAIL"
    print(f"{mark} [{result.failure_class}] {result.id} ({result.steps} steps, {result.duration_ms}ms)")
    for failure in result.failures:
        print(f"       {failure}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.runner")
    parser.add_argument("--mode", default="twin", choices=("twin", "live"))
    parser.add_argument("--only")
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--include-undo-ops", action="store_true")
    args = parser.parse_args(argv)

    try:
        _load_track_a()
    except ImportError as exc:
        print(f"track A modules are not importable yet: {exc}")
        return 2

    payload = run_all(label=args.label, mode=args.mode, only=args.only, matrix=args.matrix,
                      include_undo_ops=args.include_undo_ops, on_result=_print)
    totals = payload["totals"]
    print(f"\n{totals['passed']}/{totals['scenarios']} scenarios pass ({totals['rate']:.0%})")
    for cls, row in payload["by_class"].items():
        print(f"  {cls} {row['name']:<34} {row['passed']}/{row['total']}")
    if payload["matrix"]:
        passed = sum(1 for r in payload["matrix"] if r["passed"])
        print(f"  matrix {passed}/{len(payload['matrix'])}")
    print(f"\nwritten to evals/results/{args.label}.json")
    return 0 if totals["passed"] == totals["scenarios"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
