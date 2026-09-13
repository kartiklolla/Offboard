from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Optional

from adapters.base import RISK
from adapters.registry import Drivers, build_drivers
from agent.loop import RunConfig, run_offboarding
from agent.model import MODELS, build_model
from core import gate as G
from core.budget import Budget, BudgetExceeded
from core.replay import OFF, RECORD, REPLAY, Cassette
from core.trace import Tracer, load_trace, render_tree
from twins.faults import FaultPlan
from twins.state import TwinState, fixture_path

EXIT = {"clean": 0, "dry_run": 0, "dirty": 1, "needs_human": 2}


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def emit(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def parse_approvals(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    if raw.strip() == "all":
        return {G.APPROVE_ALL}
    return {t.strip() for t in raw.split(",") if t.strip()}


def parse_faults(specs: list[str]) -> FaultPlan:
    faults = []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) < 2:
            raise SystemExit(f"--fault expects op:mode[:on_call[:key=value]], got {spec!r}")
        fault: dict[str, Any] = {"op": parts[0], "mode": parts[1]}
        if len(parts) > 2 and parts[2]:
            fault["on_call"] = int(parts[2])
        if len(parts) > 3:
            fault["match"] = dict(kv.split("=", 1) for kv in parts[3:] if "=" in kv)
        faults.append(fault)
    return FaultPlan.from_specs(faults)


def load_hr(args: argparse.Namespace, state: Optional[TwinState]) -> list[dict]:
    if args.hr:
        with open(args.hr, encoding="utf-8") as fh:
            data = json.load(fh)
        return data["people"] if isinstance(data, dict) else data
    if state is not None:
        return state.data["people"]
    with open(fixture_path(args.seed), encoding="utf-8") as fh:
        return json.load(fh)["people"]


def build(args: argparse.Namespace, dry_run: bool, approvals: set[str], strict: bool = False, state: Optional[TwinState] = None) -> tuple[Tracer, Drivers, G.Gate, Any, RunConfig, Optional[Cassette]]:
    budget = Budget(max_live_calls=args.max_live_calls, max_writes=args.max_writes)
    if os.path.exists(args.trace) and not getattr(args, "append", False):
        os.remove(args.trace)
    tracer = Tracer(path=args.trace, mode=args.mode, budget=budget)
    cassette: Optional[Cassette] = None
    if args.mode == "twin":
        state = state or TwinState.seed(args.seed)
        drivers = build_drivers("twin", tracer=tracer, state=state, faults=parse_faults(args.fault or []))
    else:
        if args.record:
            cassette = Cassette(args.record, RECORD)
        elif args.replay:
            cassette = Cassette(args.replay, REPLAY)
        drivers = build_drivers("live", tracer=tracer, cassette=cassette)
    gate = G.Gate(tracer, approvals, dry_run=dry_run, strict=strict, sleeper=time.sleep if args.mode == "live" else (lambda s: None))
    model = build_model(args.model)
    apps = chosen_apps(args)
    config = RunConfig(
        target_email=args.user,
        hr=load_hr(args, drivers.state),
        manager_email=args.manager,
        evidence_sheet_id=args.sheet if args.sheet != "none" and "sheets" in apps else None,
        summary_channel=args.channel if args.channel != "none" else None,
        apps=apps,
    )
    return tracer, drivers, gate, model, config, cassette


def chosen_apps(args: argparse.Namespace) -> tuple[str, ...]:
    if getattr(args, "apps", None):
        return tuple(a.strip() for a in args.apps.split(",") if a.strip())
    if args.mode == "live" and not os.environ.get("GOOGLE_REFRESH_TOKEN"):
        return ("github", "slack")
    return ("github", "slack", "drive", "sheets")


def finish(tracer: Tracer, drivers: Drivers, cassette: Optional[Cassette], args: argparse.Namespace, quiet: bool = False) -> int:
    tracer.close()
    if cassette is not None:
        cassette.save()
    steps = load_trace(tracer.path)
    if drivers.state is not None and args.save_state:
        with open(args.save_state, "w", encoding="utf-8") as fh:
            json.dump(drivers.state.snapshot(), fh, indent=1, sort_keys=True)
    status = next((s["name"] for s in reversed(steps) if s["kind"] == "run_status"), "needs_human")
    if not quiet:
        emit(render_tree(steps))
        last = next((s for s in reversed(steps) if s["kind"] == "run_status"), None)
        emit("")
        emit(f"run {tracer.run_id}: {status} {json.dumps(last['result'], sort_keys=True) if last else ''}")
        emit(f"trace: {tracer.path}")
        if drivers.state is not None and args.save_state:
            emit(f"state: {args.save_state}")
    return EXIT.get(status, 2)


def cmd_run(args: argparse.Namespace) -> int:
    tracer, drivers, gate, model, config, cassette = build(args, dry_run=args.dry_run, approvals=parse_approvals(args.approve))
    try:
        run_offboarding(config, drivers, model, tracer, gate)
    except BudgetExceeded as exc:
        tracer.event("run_status", "dirty", result={"reason": f"budget exceeded: {exc}"})
    return finish(tracer, drivers, cassette, args)


def plan_entries(steps: list[dict]) -> list[dict]:
    entries = []
    for s in steps:
        if s["kind"] != "gate" or s["name"].split(":", 1)[0] not in ("transfer", "revoke"):
            continue
        entries.append({
            "approved": True,
            "hash": s["args"]["hash"],
            "name": s["name"],
            "app": s["args"]["app"],
            "op": s["args"]["op"],
            "risk": s.get("risk"),
            "diff": s.get("dry_run"),
            "item_key": s["args"].get("item_key"),
            "undo": s.get("undo"),
            "step": s["step"],
        })
    return entries


def cmd_plan(args: argparse.Namespace) -> int:
    tracer, drivers, gate, model, config, cassette = build(args, dry_run=True, approvals=set())
    run_offboarding(config, drivers, model, tracer, gate)
    code = finish(tracer, drivers, cassette, args, quiet=True)
    steps = load_trace(tracer.path)
    entries = plan_entries(steps)
    escalated = [s for s in steps if s["kind"] == "disposition" and s["result"]["disposition"] in ("escalate", "needs_human")]
    plan = {
        "target": args.user,
        "mode": args.mode,
        "model": args.model,
        "trace": tracer.path,
        "instructions": "Delete an entry, or set approved to false, to keep that write from happening. offboard apply executes only entries whose hash is present and approved.",
        "actions": entries,
        "escalated": [{"key": s["name"], "reason": s["result"]["reason"]} for s in escalated],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    emit(render_tree([s for s in steps if s["kind"] in ("run", "phase", "gate", "finding", "identity")]))
    emit("")
    emit(f"plan: {len(entries)} writes, {len(escalated)} escalated, nothing applied -> {args.out}")
    return code


def cmd_apply(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    approved = {e["hash"] for e in plan.get("actions", []) if e.get("approved", True)}
    dropped = [e["name"] for e in plan.get("actions", []) if not e.get("approved", True)]
    args.user = args.user or plan["target"]
    tracer, drivers, gate, model, config, cassette = build(args, dry_run=False, approvals=approved, strict=True)
    tracer.event("plan", "loaded", args={"path": args.plan, "approved": len(approved), "explicitly_unapproved": dropped})
    try:
        run_offboarding(config, drivers, model, tracer, gate)
    except BudgetExceeded as exc:
        tracer.event("run_status", "dirty", result={"reason": f"budget exceeded: {exc}"})
    return finish(tracer, drivers, cassette, args)


UNDO_APPLY: dict[str, Callable[[Drivers, dict], Any]] = {
    "add_collaborator": lambda d, a: d.github.add_collaborator(a["repo"], a["login"], a["permission"]),
    "add_permission": lambda d, a: d.drive.add_permission(a["file"], a["email"], a["role"]),
    "transfer_ownership": lambda d, a: d.drive.transfer_ownership(a["file"], a["new_owner"]),
    "invite_to_channel": lambda d, a: d.slack.invite_to_channel(a["channel"], a["user"]),
    "reactivate_user": lambda d, a: d.slack.reactivate_user(a["user"]),
}

UNDO_CHECKS: dict[str, Callable[[Drivers, dict], tuple[Callable[[], Any], Callable[[], Any]]]] = {
    "add_collaborator": lambda d, a: (
        lambda: not any(c["login"] == a["login"] for c in d.github.all_collaborators(a["repo"])),
        lambda: any(c["login"] == a["login"] for c in d.github.all_collaborators(a["repo"])),
    ),
    "add_permission": lambda d, a: (
        lambda: not any(p["email"] == a["email"] for p in d.drive.all_permissions(a["file"])),
        lambda: any(p["email"] == a["email"] for p in d.drive.all_permissions(a["file"])),
    ),
    "transfer_ownership": lambda d, a: (
        lambda: d.drive.get_file(a["file"])["owner"] != a["new_owner"],
        lambda: d.drive.get_file(a["file"])["owner"] == a["new_owner"],
    ),
    "invite_to_channel": lambda d, a: (
        lambda: a["user"] not in d.slack.all_channel_members(a["channel"]),
        lambda: a["user"] in d.slack.all_channel_members(a["channel"]),
    ),
    "reactivate_user": lambda d, a: (
        lambda: d.slack.get_user(a["user"]).get("deleted", False) is True,
        lambda: d.slack.get_user(a["user"]).get("deleted", False) is False,
    ),
}


def cmd_undo(args: argparse.Namespace) -> int:
    source = load_trace(args.trace)
    applied = [s for s in source if s["kind"] == "gate" and s.get("result", {}).get("status") == "applied" and s["name"].split(":", 1)[0] in ("transfer", "revoke")]
    state = None
    if args.mode == "twin":
        if not args.state:
            raise SystemExit("undo on twins needs --state <file saved by run --save-state>, otherwise the twin starts from the pristine fixture and nothing is there to undo")
        with open(args.state, encoding="utf-8") as fh:
            state = TwinState(json.load(fh))
    args.trace = args.out_trace
    tracer, drivers, gate, model, config, cassette = build(args, dry_run=args.dry_run, approvals=parse_approvals(args.approve) or {G.APPROVE_ALL}, state=state)
    with tracer.step("run", f"undo:{os.path.basename(args.trace)}", args={"source_trace": source[0]["run_id"] if source else None, "applied_steps": len(applied)}):
        restored = skipped = failed = 0
        for s in reversed(applied):
            undo = s.get("undo") or {}
            op = undo.get("op")
            uargs = dict(undo.get("args") or {})
            resource = s["name"].split(":", 1)[1]
            if not undo.get("supported", True) or op not in UNDO_APPLY or op not in RISK:
                tracer.event("skipped", f"undo:{resource}", args={"op": op, "source_step": s["step"]}, note=undo.get("note") or "no supported undo for this operation")
                skipped += 1
                continue
            pre, post = UNDO_CHECKS[op](drivers, uargs)
            action = G.Action(s["args"]["app"], op, uargs, RISK[op], resource, "undo", s["args"].get("item_key"))
            result = gate.execute(
                action,
                precondition=pre,
                describe=lambda op=op, uargs=uargs, resource=resource: f"+undo {op} {json.dumps(uargs, sort_keys=True)} on {resource}",
                apply=lambda op=op, uargs=uargs: UNDO_APPLY[op](drivers, uargs),
                postcondition=post,
                undo={"op": s["args"]["op"], "args": {k: v for k, v in s["args"].items() if k not in ("app", "op", "item_key", "hash")}, "note": "re-applying the original revoke"},
            )
            if result.status == G.APPLIED:
                restored += 1
            elif result.status in (G.FAILED_APPLY, G.FAILED_POSTCONDITION):
                failed += 1
    status = "clean" if failed == 0 else "dirty"
    tracer.event("run_status", status, result={"restored": restored, "skipped_unsupported": skipped, "failed": failed, "source_applied": len(applied)})
    return finish(tracer, drivers, cassette, args)


def add_common(p: argparse.ArgumentParser, needs_user: bool = True) -> None:
    p.add_argument("--user", required=needs_user, help="email of the departing employee")
    p.add_argument("--mode", choices=("twin", "live"), default="twin")
    p.add_argument("--model", choices=MODELS, default="heuristic")
    p.add_argument("--seed", default="acme", help="fixture name for twin mode")
    p.add_argument("--hr", help="JSON file with the HR directory (defaults to the fixture's people)")
    p.add_argument("--manager", help="override the manager who receives transferred files")
    p.add_argument("--sheet", default=os.environ.get("GOOGLE_SHEET_ID") or "SHEET_EVIDENCE", help="evidence sheet id, or 'none'")
    p.add_argument("--channel", default="it-offboarding", help="summary channel name, or 'none'")
    p.add_argument("--apps", help="comma-separated subset of github,slack,drive,sheets; live mode drops drive and sheets when Google is not configured")
    p.add_argument("--trace", default="traces/run.jsonl")
    p.add_argument("--append", action="store_true", help="append to an existing trace file instead of starting fresh")
    p.add_argument("--save-state", help="twin mode: write the end state to this file (needed for undo)")
    p.add_argument("--fault", action="append", help="twin mode: op:mode[:on_call[:key=value...]], repeatable")
    p.add_argument("--record", help="live mode: record API responses to this cassette")
    p.add_argument("--replay", help="live mode: replay API responses from this cassette instead of the network")
    p.add_argument("--max-live-calls", type=int, default=300)
    p.add_argument("--max-writes", type=int, default=60)


def main(argv: Optional[list[str]] = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="offboard", description="Revoke a departing employee's access across GitHub, Slack, Google Drive and Sheets, and prove it was done safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="resolve, inventory, classify, plan, execute, report")
    add_common(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="produce every diff, apply nothing")
    p_run.add_argument("--approve", help="'all', or comma-separated tokens: app names, verbs, app:op:resource, action hashes")
    p_run.set_defaults(func=cmd_run)

    p_plan = sub.add_parser("plan", help="dry run that writes an editable plan file")
    add_common(p_plan)
    p_plan.add_argument("--out", default="plan.json")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="execute only the writes whose hash is in the plan file")
    add_common(p_apply, needs_user=False)
    p_apply.add_argument("--plan", default="plan.json")
    p_apply.set_defaults(func=cmd_apply, dry_run=False)

    p_undo = sub.add_parser("undo", help="replay the undo records of an earlier trace through the gate")
    add_common(p_undo, needs_user=False)
    p_undo.add_argument("--state", help="twin mode: end-state file written by run --save-state")
    p_undo.add_argument("--out-trace", default="traces/undo.jsonl")
    p_undo.add_argument("--dry-run", action="store_true")
    p_undo.add_argument("--approve", help="defaults to all")
    p_undo.set_defaults(func=cmd_undo)

    args = parser.parse_args(argv)
    if args.command == "undo" and not args.user:
        args.user = "undo@local"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
