from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from adapters.base import AccessItem, Identity, IncompleteRead
from adapters.registry import Drivers
from agent import policy as P
from agent import tools
from core import gate as G
from core.budget import BudgetExceeded
from core.trace import Tracer

APPS = ("github", "slack", "drive")

CLEAN, DIRTY, NEEDS_HUMAN, DRY_RUN = "clean", "dirty", "needs_human", "dry_run"


@dataclass
class RunConfig:
    target_email: str
    hr: list[dict]
    manager_email: Optional[str] = None
    evidence_sheet_id: Optional[str] = "SHEET_EVIDENCE"
    summary_channel: Optional[str] = "it-offboarding"
    apps: tuple[str, ...] = APPS
    plan_only: bool = False
    approved_hashes: Optional[set[str]] = None


@dataclass
class RunState:
    hr_record: dict
    identities: dict[str, Identity] = field(default_factory=dict)
    identity_steps: dict[str, int] = field(default_factory=dict)
    items: list[AccessItem] = field(default_factory=list)
    dispositions: dict[str, P.Disposition] = field(default_factory=dict)
    disposition_steps: dict[str, int] = field(default_factory=dict)
    planned: list[tools.PlannedAction] = field(default_factory=list)
    results: list[G.GateResult] = field(default_factory=list)
    failed: Optional[G.GateResult] = None
    skipped: list[str] = field(default_factory=list)
    run_step_id: int = 0


def run_offboarding(config: RunConfig, drivers: Drivers, model: Any, tracer: Tracer, gate: G.Gate) -> None:
    state: Optional[RunState] = None
    with tracer.step("run", f"offboard:{config.target_email}", args={"mode": drivers.mode, "model": model.name, "dry_run": gate.dry_run}) as run_step:
        hr_record = next((p for p in config.hr if p.get("email", "").lower() == config.target_email.lower()), None)
        if hr_record is None:
            tracer.finding("F1", "override:identity:hr", args={"target": config.target_email}, note="target not in the HR directory; nothing done")
        else:
            hr_record = dict(hr_record)
            if config.manager_email:
                hr_record["manager"] = config.manager_email
            state = RunState(hr_record=hr_record, run_step_id=run_step.step)
            policy = P.Policy(tracer, hr_record, config.hr, capabilities={"slack_deactivation": getattr(drivers.slack, "supports_deactivation", True)})

            _resolve_identity(config, drivers, model, tracer, policy, state)
            _inventory(config, drivers, tracer, state)
            _classify(model, tracer, policy, state)
            _plan(drivers, model, tracer, policy, state)
            if not config.plan_only:
                _execute(gate, tracer, state)
                _report(config, drivers, model, tracer, policy, gate, state)
    if state is None:
        tracer.event("run_status", NEEDS_HUMAN, result={"applied": 0, "failed": 0, "escalated": 0, "reason": "target not in HR directory"})
    else:
        _finish(gate, tracer, state)


def _model_call(tracer: Tracer, model: Any, method: str, *args: Any) -> Any:
    with tracer.step("model_call", method, model=model.name) as step:
        out = getattr(model, method)(*args)
        call = getattr(model, "last_call", None)
        if call is not None:
            step.record(prompt_hash=call.prompt_hash, tokens=call.tokens, cost_usd=call.cost_usd)
        step.record(result=_short(out))
    return out


def _short(out: Any) -> Any:
    if isinstance(out, list):
        return {"count": len(out)}
    if isinstance(out, dict):
        return {k: v for k, v in out.items() if k in ("pick", "confidence", "injection_suspected")}
    return out


def _candidates(app: str, drivers: Drivers, hr_record: dict) -> list[dict]:
    if app == "github":
        return [{"id": m["login"], "handle": m["login"], "name": m.get("name"), "email": m.get("email")} for m in drivers.github.all_org_members()]
    if app == "slack":
        return [{"id": u["id"], "handle": u.get("name"), "name": u.get("real_name"), "email": u.get("email")} for u in drivers.slack.all_users() if not u.get("is_bot")]
    if app == "drive":
        return [{"id": hr_record["email"], "handle": None, "name": None, "email": hr_record["email"]}]
    return []


def _resolve_identity(config: RunConfig, drivers: Drivers, model: Any, tracer: Tracer, policy: P.Policy, state: RunState) -> None:
    with tracer.step("phase", "resolve_identity"):
        for app in config.apps:
            candidates = _candidates(app, drivers, state.hr_record)
            proposal = _model_call(tracer, model, "resolve_identity", app, state.hr_record, candidates)
            identity = policy.resolve_identity(app, candidates, proposal.get("pick"), proposal.get("reason", ""))
            state.identities[app] = identity
            ev = tracer.event(
                "identity", app,
                result={"principal_id": identity.principal_id, "status": identity.status, "signals": identity.signals, "display": identity.display, "model_said": proposal.get("pick")},
            )
            state.identity_steps[app] = ev.step


def _inventory(config: RunConfig, drivers: Drivers, tracer: Tracer, state: RunState) -> None:
    with tracer.step("phase", "inventory"):
        for app in config.apps:
            identity = state.identities[app]
            if not identity.resolved:
                tracer.event("inventory", app, result={"keys": [], "skipped": "identity not resolved"})
                continue
            try:
                items = drivers.by_app(app).inventory(identity, state.hr_record)
            except (BudgetExceeded, IncompleteRead):
                raise
            except Exception as exc:
                state.identities[app] = Identity(app, identity.principal_id, identity.display, identity.signals, NEEDS_HUMAN)
                tracer.finding("F6", f"unavailable:{app}", args={"error": f"{type(exc).__name__}: {str(exc)[:300]}"}, note="app could not be read; nothing on it will be touched")
                tracer.event("inventory", app, result={"keys": [], "skipped": "app unavailable"})
                continue
            state.items.extend(items)
            tracer.event("inventory", app, result={"keys": [i.key for i in items]})
        tracer.event("inventory", "all", result={"keys": [i.key for i in state.items], "count": len(state.items)})


def _classify(model: Any, tracer: Tracer, policy: P.Policy, state: RunState) -> None:
    with tracer.step("phase", "classify"):
        views = [{**it.to_dict(), "content": it.content, "content_field": it.content_field} for it in state.items]
        proposals = _model_call(tracer, model, "classify", views, state.hr_record) if views else []
        state.dispositions = policy.enforce(state.items, proposals)
        for item in state.items:
            d = state.dispositions[item.key]
            ev = tracer.event("disposition", item.key, result=d.to_dict())
            state.disposition_steps[item.key] = ev.step


def _plan(drivers: Drivers, model: Any, tracer: Tracer, policy: P.Policy, state: RunState) -> None:
    with tracer.step("phase", "plan"):
        slack_id = state.identities.get("slack")
        hr_ctx = {**state.hr_record, "slack_user_id": slack_id.principal_id if slack_id else None}
        planned: list[tools.PlannedAction] = []
        for item in state.items:
            planned.extend(tools.actions_for(item, state.dispositions[item.key], drivers, hr_ctx))
        proposed = _model_call(tracer, model, "order", [p.view() for p in planned]) if planned else []
        ordered_actions = policy.enforce_order([p.action for p in planned], proposed)
        by_name = {p.name: p for p in planned}
        state.planned = [by_name[a.name] for a in ordered_actions]
        tracer.event("plan", "actions", result={"order": [p.name for p in state.planned], "count": len(state.planned)})


def _execute(gate: G.Gate, tracer: Tracer, state: RunState) -> None:
    with tracer.step("phase", "execute"):
        done: dict[str, str] = {}
        for p in state.planned:
            if state.failed is not None:
                state.skipped.append(p.name)
                tracer.event("skipped", p.name, note=f"not attempted: run stopped after {state.failed.action.name} {state.failed.status}")
                continue
            if p.depends_on and done.get(p.depends_on) not in (G.APPLIED, G.SKIPPED_DRY_RUN):
                state.skipped.append(p.name)
                tracer.event("skipped", p.name, note=f"depends on {p.depends_on}, which is {done.get(p.depends_on, 'not run')}")
                continue
            precondition = p.precondition
            if gate.dry_run and p.depends_on:
                precondition = lambda dep=p.depends_on: f"assumed: runs after {dep}"
            result = gate.execute(p.action, precondition, p.describe, p.apply, p.postcondition, p.undo)
            state.results.append(result)
            done[p.name] = result.status
            if result.status in (G.FAILED_APPLY, G.FAILED_POSTCONDITION):
                state.failed = result
                undo_records = [{"step": r.step_id, "name": r.action.name, **r.undo} for r in state.results if r.status == G.APPLIED]
                tracer.finding(
                    "F4", "dirty_run",
                    args={"failed_step": result.step_id, "failed_status": result.status, "undo": undo_records, "applied_before_failure": len(undo_records)},
                    note="write failed; remaining writes not attempted; undo records listed for every applied step",
                )


def _report(config: RunConfig, drivers: Drivers, model: Any, tracer: Tracer, policy: P.Policy, gate: G.Gate, state: RunState) -> None:
    with tracer.step("phase", "report"):
        if config.evidence_sheet_id:
            rows = [[tracer.run_id, r.step_id, r.action.app, r.action.op, r.action.resource, r.status, r.diff, json.dumps(r.undo, sort_keys=True, default=str)] for r in state.results]
            if rows:
                p = tools.evidence_log_action(drivers, config.evidence_sheet_id, rows)
                state.results.append(gate.execute(p.action, p.precondition, p.describe, p.apply, p.postcondition, p.undo))
        if config.summary_channel:
            channel = drivers.slack.channel_by_name(config.summary_channel)
            if channel is None:
                tracer.event("summary", "suppressed", result={"sentences": [], "dropped": [], "ts": None, "reason": f"channel {config.summary_channel} not found"})
                return
            context = _summary_context(state, tracer)
            sentences = _model_call(tracer, model, "draft_summary", context)
            kept, dropped = policy.verify_summary(sentences, tracer.steps)
            if not kept:
                kept = [f"Offboarding run for {state.hr_record['name']} finished with status {_status(gate, state)}; see the trace for details. [s{state.run_step_id}]"]
            text = "\n".join(kept)
            posted: dict[str, Any] = {}
            p = tools.summary_action(drivers, channel, text, posted)
            result = gate.execute(p.action, p.precondition, p.describe, p.apply, p.postcondition, p.undo)
            state.results.append(result)
            tracer.event("summary", "posted" if result.status == G.APPLIED else "suppressed", result={"sentences": kept, "dropped": dropped, "ts": posted.get("ts"), "gate_status": result.status})


def _summary_context(state: RunState, tracer: Tracer) -> dict:
    return {
        "target": {k: state.hr_record.get(k) for k in ("name", "email", "title")},
        "run_step_id": state.run_step_id,
        "gate_results": [
            {"name": r.action.name, "app": r.action.app, "verb": r.action.verb, "status": r.status, "step_id": r.step_id, "shared": _shared_count(state, r)}
            for r in state.results
        ],
        "escalations": [
            {"key": k, "reason": d.reason, "step_id": state.disposition_steps[k]}
            for k, d in state.dispositions.items() if d.disposition in (P.ESCALATE, P.NEEDS_HUMAN)
        ],
        "identity": [{"app": app, "status": i.status, "step_id": state.identity_steps[app]} for app, i in state.identities.items()],
        "skipped": list(state.skipped),
        "findings": [{"step": s.step, "class": s.failure_class, "name": s.name} for s in tracer.steps if s.kind == "finding"],
    }


def _shared_count(state: RunState, r: G.GateResult) -> int:
    item = next((i for i in state.items if i.key == r.action.item_key), None)
    return len(item.shared_with) if item else 0


def _status(gate: G.Gate, state: RunState) -> str:
    if gate.dry_run:
        return DRY_RUN
    if state.failed is not None:
        return DIRTY
    if any(not i.resolved for i in state.identities.values()) or any(r.status == G.NEEDS_APPROVAL for r in state.results):
        return NEEDS_HUMAN
    return CLEAN


def _finish(gate: G.Gate, tracer: Tracer, state: RunState) -> None:
    status = DRY_RUN if gate.dry_run else _status(gate, state)
    write_results = [r for r in state.results if r.action.verb in ("transfer", "revoke")]
    tracer.event(
        "run_status", status,
        result={
            "applied": sum(1 for r in write_results if r.status == G.APPLIED),
            "failed": sum(1 for r in write_results if r.status in (G.FAILED_APPLY, G.FAILED_POSTCONDITION)),
            "needs_approval": sum(1 for r in write_results if r.status == G.NEEDS_APPROVAL),
            "escalated": sum(1 for d in state.dispositions.values() if d.disposition in (P.ESCALATE, P.NEEDS_HUMAN)),
            "skipped": len(state.skipped),
            "unresolved_apps": [app for app, i in state.identities.items() if not i.resolved],
        },
    )
