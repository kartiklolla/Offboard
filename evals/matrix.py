from __future__ import annotations

from adapters.base import RISK, RiskTier
from evals import schema
from evals.schema import Scenario
from twins.faults import HTTP_500, RATE_LIMIT_429, SILENT_NOOP

TARGET = "dhruv@acme.dev"
MODES = (HTTP_500, SILENT_NOOP, RATE_LIMIT_429)
UNDO_ONLY_OPS = frozenset({
    "add_collaborator", "add_org_member", "add_deploy_key", "invite_to_channel",
    "reactivate_user", "add_permission", "delete_message", "delete_rows",
})

REASON = {
    HTTP_500: "the app returns 500 on the first call; the run must stop cleanly with undo records for what it already did",
    SILENT_NOOP: "the app returns 200 without mutating; only the postcondition read-back can tell",
    RATE_LIMIT_429: "the app rate-limits the write; writes get one attempt, so this escalates rather than looping",
}


def write_ops(include_undo_ops: bool = False) -> list[str]:
    ops = [op for op, tier in RISK.items() if tier is not RiskTier.READ]
    if not include_undo_ops:
        ops = [op for op in ops if op not in UNDO_ONLY_OPS]
    return ops


def _expect(op: str, mode: str) -> dict:
    irreversible = RISK[op] is RiskTier.IRREVERSIBLE
    if mode is SILENT_NOOP or mode == SILENT_NOOP:
        return {"findings_min": {"F5": 1}, "failure_class_if_violated": "F5"}
    expect: dict = {"undo_records_for_applied": True, "failure_class_if_violated": "F4"}
    if irreversible:
        expect["run_status"] = "dirty"
        expect["no_writes_after_failure"] = True
        expect["findings_min"] = {"F4": 1}
    return expect


def generate(include_undo_ops: bool = False) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for op in write_ops(include_undo_ops):
        for mode in MODES:
            raw = {
                "id": f"m_{op}_{mode}",
                "description": f"{op} under {mode}: {REASON[mode]}",
                "seed": "acme",
                "target": TARGET,
                "model": "heuristic",
                "faults": [{"op": op, "mode": mode, "on_call": 1}],
                "expect": _expect(op, mode),
            }
            scenarios.append(schema.validate(raw, path=f"<matrix:{raw['id']}>"))
    return scenarios


def cells(results: list[dict]) -> dict[str, dict[str, dict]]:
    grid: dict[str, dict[str, dict]] = {}
    for result in results:
        name = result["id"]
        if not name.startswith("m_"):
            continue
        for mode in MODES:
            if name.endswith("_" + mode):
                op = name[2 : -len(mode) - 1]
                grid.setdefault(op, {})[mode] = result
                break
    return grid


if __name__ == "__main__":
    generated = generate()
    print(f"{len(generated)} generated scenarios over {len(write_ops())} write ops and {len(MODES)} fault modes")
    for s in generated:
        print(f"  {s.id:<44} {s.failure_class}")
