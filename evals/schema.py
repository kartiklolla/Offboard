from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from twins.faults import MODES

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "scenarios")

FAILURE_CLASSES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "H")
DISPOSITIONS = ("revoke", "transfer_then_revoke", "escalate", "needs_human", "keep")
GATE_STATUSES = ("applied", "skipped_dry_run", "blocked_precondition", "needs_approval", "failed_postcondition", "failed_apply")
MODELS = ("heuristic", "gullible", "anthropic")


class ScenarioError(ValueError):
    pass


@dataclass
class Expect:
    failure_class_if_violated: str
    dispositions: dict[str, str] = field(default_factory=dict)
    order_before: list[tuple[str, str]] = field(default_factory=list)
    postconditions: list[dict] = field(default_factory=list)
    forbidden_calls: list[str] = field(default_factory=list)
    required_calls: list[str] = field(default_factory=list)
    identity: dict[str, str] = field(default_factory=dict)
    inventory_contains: list[str] = field(default_factory=list)
    findings_min: dict[str, int] = field(default_factory=dict)
    gate_status: dict[str, str] = field(default_factory=dict)
    run_status: Optional[str] = None
    undo_records_for_applied: bool = False
    no_writes_after_failure: bool = False
    report_cited: bool = False
    evidence_rows_match_gate_steps: bool = False


@dataclass
class Scenario:
    id: str
    seed: str
    target: str
    expect: Expect
    faults: list[dict] = field(default_factory=list)
    patch: list[dict] = field(default_factory=list)
    model: str = "heuristic"
    dry_run: bool = False
    approvals: list[str] = field(default_factory=lambda: ["*"])
    description: str = ""

    @property
    def failure_class(self) -> str:
        return self.expect.failure_class_if_violated


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ScenarioError(msg)


def validate(raw: dict, path: str = "<inline>") -> Scenario:
    where = f"{path}: "
    for key in ("id", "seed", "target", "expect"):
        _require(key in raw, where + f"missing required key {key!r}")
    _require(isinstance(raw["id"], str) and raw["id"], where + "id must be a non-empty string")
    _require("@" in raw["target"], where + "target must be an email")

    faults = raw.get("faults", [])
    _require(isinstance(faults, list), where + "faults must be a list")
    for f in faults:
        _require("op" in f and "mode" in f, where + "each fault needs op and mode")
        _require(f["mode"] in MODES, where + f"unknown fault mode {f['mode']!r}")
        _require(isinstance(f.get("on_call", 1), int) and f.get("on_call", 1) >= 1, where + "on_call must be an int >= 1")
        _require(isinstance(f.get("match", {}), dict), where + "match must be an object")

    patch = raw.get("patch", [])
    for p in patch:
        _require(p.get("op") in ("set", "delete") and "path" in p, where + "patch entries need op in (set, delete) and path")
        _require(p["op"] == "delete" or "value" in p, where + "set patch needs a value")

    model = raw.get("model", "heuristic")
    _require(model in MODELS, where + f"model must be one of {MODELS}")

    e = raw["expect"]
    _require(e.get("failure_class_if_violated") in FAILURE_CLASSES, where + f"failure_class_if_violated must be one of {FAILURE_CLASSES}")
    for key, disp in e.get("dispositions", {}).items():
        _require(key.count(":") >= 2, where + f"disposition key {key!r} must be app:kind:resource")
        _require(disp in DISPOSITIONS, where + f"disposition {disp!r} for {key!r} not in {DISPOSITIONS}")
    order_before = []
    for pair in e.get("order_before", []):
        _require(isinstance(pair, list) and len(pair) == 2, where + "order_before entries are [before, after] pairs")
        order_before.append((pair[0], pair[1]))
    for pc in e.get("postconditions", []):
        _require({"actor", "resource", "has_access"} <= set(pc), where + "postconditions need actor, resource, has_access")
        _require(isinstance(pc["has_access"], bool), where + "has_access must be a bool")
    for call in e.get("forbidden_calls", []) + e.get("required_calls", []):
        _require(":" in call, where + f"call spec {call!r} must be op:resource")
    for name, status in e.get("gate_status", {}).items():
        _require(status in GATE_STATUSES, where + f"gate_status {status!r} for {name!r} not in {GATE_STATUSES}")
    for cls, n in e.get("findings_min", {}).items():
        _require(cls in FAILURE_CLASSES and isinstance(n, int), where + "findings_min maps failure class to int")
    for app, who in e.get("identity", {}).items():
        _require(app in ("github", "slack", "drive"), where + f"identity app {app!r} unknown")
        _require(isinstance(who, str), where + "identity value is a principal id or 'needs_human'")

    expect = Expect(
        failure_class_if_violated=e["failure_class_if_violated"],
        dispositions=dict(e.get("dispositions", {})),
        order_before=order_before,
        postconditions=list(e.get("postconditions", [])),
        forbidden_calls=list(e.get("forbidden_calls", [])),
        required_calls=list(e.get("required_calls", [])),
        identity=dict(e.get("identity", {})),
        inventory_contains=list(e.get("inventory_contains", [])),
        findings_min=dict(e.get("findings_min", {})),
        gate_status=dict(e.get("gate_status", {})),
        run_status=e.get("run_status"),
        undo_records_for_applied=bool(e.get("undo_records_for_applied", False)),
        no_writes_after_failure=bool(e.get("no_writes_after_failure", False)),
        report_cited=bool(e.get("report_cited", False)),
        evidence_rows_match_gate_steps=bool(e.get("evidence_rows_match_gate_steps", False)),
    )
    return Scenario(
        id=raw["id"], seed=raw["seed"], target=raw["target"], expect=expect,
        faults=faults, patch=patch, model=model, dry_run=bool(raw.get("dry_run", False)),
        approvals=list(raw.get("approvals", ["*"])), description=raw.get("description", ""),
    )


def load(path: str) -> Scenario:
    with open(path, encoding="utf-8") as fh:
        return validate(json.load(fh), path)


def load_all(directory: str = SCENARIOS_DIR) -> list[Scenario]:
    scenarios = [load(os.path.join(directory, name)) for name in sorted(os.listdir(directory)) if name.endswith(".json")]
    ids = [s.id for s in scenarios]
    dupes = {i for i in ids if ids.count(i) > 1}
    _require(not dupes, f"duplicate scenario ids: {sorted(dupes)}")
    return scenarios
