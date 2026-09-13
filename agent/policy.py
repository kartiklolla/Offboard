from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from adapters.base import AccessItem, Identity
from core.trace import Tracer

REVOKE = "revoke"
TRANSFER_THEN_REVOKE = "transfer_then_revoke"
ESCALATE = "escalate"
NEEDS_HUMAN = "needs_human"
KEEP = "keep"
DISPOSITIONS = (REVOKE, TRANSFER_THEN_REVOKE, ESCALATE, NEEDS_HUMAN, KEEP)

DESTRUCTIVENESS = {KEEP: 0, NEEDS_HUMAN: 0, ESCALATE: 0, TRANSFER_THEN_REVOKE: 1, REVOKE: 2}

STRONG_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"offboarding agent\s*[:,\-]",
        r"(to|for) (the )?(automated )?offboarding agent",
        r"exempt from offboarding",
        r"mark all items (as )?complete",
        r"ignore (all |any )?(previous|prior|above) instructions",
    )
]
WEAK_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"skip (the )?revocation",
        r"do not (transfer|revoke|remove)",
        r"account .{0,40} is exempt",
    )
]

COMPLETION_VERBS = re.compile(r"\b(revoked|removed|transferred|completed|applied|deactivated|deleted|kicked|posted|logged|done|fully)\b", re.I)
CITATION = re.compile(r"\[s(\d+)\]\s*$")

MIN_SIGNALS = 2
CREDENTIAL_FRESH_HOURS = 24.0

PHASE_RANK = {"transfer": 0, "revoke_reversible": 1, "revoke_irreversible": 2, "deactivate": 3, "log": 4, "notify": 5}
ACCOUNT_LEVEL_OPS = ("deactivate_user", "remove_org_member")


@dataclass
class Disposition:
    disposition: str
    reason: str
    source: str
    rule: Optional[str] = None
    transfer_to: Optional[str] = None
    model_said: Optional[str] = None
    injection: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "disposition": self.disposition,
            "reason": self.reason,
            "source": self.source,
            "rule": self.rule,
            "transfer_to": self.transfer_to,
            "model_said": self.model_said,
            "injection": list(self.injection),
        }


def detect_injection(text: Optional[str]) -> list[str]:
    if not text:
        return []
    strong = [p.pattern for p in STRONG_INJECTION if p.search(text)]
    weak = [p.pattern for p in WEAK_INJECTION if p.search(text)]
    if strong or len(weak) >= 2:
        return strong + weak
    return []


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def signals(app: str, candidate: dict, hr_record: dict) -> set[str]:
    found: set[str] = set()
    if candidate.get("email") and _norm(candidate["email"]) == _norm(hr_record.get("email")):
        found.add("email")
        if app == "drive":
            found.add("directory")
    if candidate.get("name") and _norm(candidate["name"]) == _norm(hr_record.get("name")):
        found.add("name")
    recorded = hr_record.get("github_login") if app == "github" else hr_record.get(f"{app}_handle")
    if recorded and candidate.get("handle") and _norm(candidate["handle"]) == _norm(recorded):
        found.add("handle")
    return found


class Policy:
    def __init__(self, tracer: Tracer, hr_record: dict, hr: Iterable[dict] = (), capabilities: Optional[dict] = None) -> None:
        self.tracer = tracer
        self.hr_record = hr_record
        self.hr = list(hr)
        self.manager = hr_record.get("manager")
        self.capabilities = {"slack_deactivation": True, **(capabilities or {})}

    def resolve_identity(self, app: str, candidates: list[dict], model_pick: Optional[str], model_reason: str = "") -> Identity:
        scored = {c["id"]: signals(app, c, self.hr_record) for c in candidates}
        qualified = [cid for cid, s in scored.items() if len(s) >= MIN_SIGNALS]
        by_id = {c["id"]: c for c in candidates}

        if len(qualified) == 1:
            pick = qualified[0]
            status = "resolved"
        else:
            pick = None
            status = NEEDS_HUMAN

        if model_pick != pick:
            prevented = "F1"
            self.tracer.finding(
                prevented,
                f"override:identity:{app}",
                args={
                    "model_said": model_pick,
                    "policy_said": pick,
                    "model_signals": sorted(scored.get(model_pick, set())) if model_pick else [],
                    "qualified": qualified,
                    "model_reason": model_reason,
                },
                note="model pick rejected: fewer than two independent signals" if model_pick and len(scored.get(model_pick, set())) < MIN_SIGNALS else "policy and model disagree on identity",
            )

        display = by_id[pick].get("name") or by_id[pick].get("handle") or pick if pick else "unresolved"
        return Identity(app=app, principal_id=pick, display=str(display), signals=sorted(scored.get(pick, set())) if pick else [], status=status)

    def rule_for(self, item: AccessItem) -> Disposition:
        kind = item.kind
        if kind == "deploy_key":
            used_by = item.hints.get("used_by") or []
            age = item.hints.get("age_hours")
            if used_by:
                return Disposition(ESCALATE, f"referenced by {', '.join(used_by)}; deleting it would break automation", "policy", "R2")
            if age is not None and age < CREDENTIAL_FRESH_HOURS:
                return Disposition(ESCALATE, f"used {age}h ago; something still depends on it", "policy", "R2")
            return Disposition(REVOKE, "personal credential, not referenced and not recently used", "policy", "R7")
        if kind in ("folder", "file"):
            if not self.manager:
                return Disposition(ESCALATE, "owned by the employee but no manager on record to receive it", "policy", "R4")
            if item.shared_with:
                return Disposition(TRANSFER_THEN_REVOKE, f"owned by the employee and shared with {len(item.shared_with)} colleagues; revoking directly would orphan it", "policy", "R3", transfer_to=self.manager)
            return Disposition(TRANSFER_THEN_REVOKE, "owned solely by the employee; ownership goes to the manager so nothing is lost", "policy", "R4", transfer_to=self.manager)
        if kind == "external_share":
            return Disposition(ESCALATE, f"shared with external party {item.hints.get('external_email')}; a human decides", "policy", "R5")
        if item.app == "slack" and kind == "user" and not self.capabilities.get("slack_deactivation", True):
            return Disposition(ESCALATE, "the Slack API cannot deactivate users on this plan (admin.users.remove needs Enterprise Grid); a workspace admin does it in the UI", "policy", "R9")
        return Disposition(REVOKE, f"{kind} held by the employee", "policy", "R8")

    def enforce(self, items: list[AccessItem], proposals: list[dict]) -> dict[str, Disposition]:
        proposed = {p["key"]: p for p in proposals}
        final: dict[str, Disposition] = {}
        for item in items:
            injected = detect_injection(item.content)
            if injected:
                self.tracer.finding(
                    "F7",
                    f"injection:{item.app}:{item.resource_name}",
                    args={"field": item.content_field, "patterns": injected, "item_key": item.key},
                    note="external content addressed the agent; logged and ignored",
                )
            rule = self.rule_for(item)
            rule.injection = injected
            p = proposed.get(item.key)
            model_said = p.get("disposition") if p else None
            if model_said == rule.disposition:
                final[item.key] = Disposition(rule.disposition, p.get("reason") or rule.reason, "model", rule.rule, rule.transfer_to, model_said, injected)
                continue
            prevented = self._class_prevented(rule, model_said, injected)
            if prevented:
                self.tracer.finding(
                    prevented,
                    f"override:{item.key}",
                    args={"model_said": model_said, "policy_said": rule.disposition, "rule": rule.rule, "model_reason": (p or {}).get("reason")},
                    note=f"policy rule {rule.rule} overrides the model",
                )
            else:
                self.tracer.event(
                    "override",
                    item.key,
                    args={"model_said": model_said, "policy_said": rule.disposition, "rule": rule.rule},
                    note="model was more cautious than the rule; rule applied, caution recorded",
                )
            rule.model_said = model_said
            final[item.key] = rule
        return final

    @staticmethod
    def _class_prevented(rule: Disposition, model_said: Optional[str], injected: list[str]) -> Optional[str]:
        if model_said is None:
            return None
        if model_said == KEEP:
            return "F7"
        if DESTRUCTIVENESS.get(model_said, 0) > DESTRUCTIVENESS[rule.disposition]:
            if rule.rule in ("R3", "R4"):
                return "F2"
            return "F3"
        if model_said == REVOKE and rule.disposition == TRANSFER_THEN_REVOKE:
            return "F2"
        return None

    def enforce_order(self, actions: list[Any], proposed: list[str]) -> list[Any]:
        by_name = {a.name: a for a in actions}
        model_order = [by_name[n] for n in proposed if n in by_name]
        missing = [a for a in actions if a.name not in set(proposed)]
        model_order.extend(missing)
        ranked = sorted(model_order, key=lambda a: (self.phase(a), model_order.index(a)))
        if [a.name for a in ranked] != [a.name for a in model_order] or missing:
            self.tracer.finding(
                "F2",
                "override:order",
                args={"model_order": [a.name for a in model_order], "policy_order": [a.name for a in ranked], "missing_from_model": [a.name for a in missing]},
                note="model order violated a phase constraint; transfers first, deactivation late, report last",
            )
        return ranked

    @staticmethod
    def phase(action: Any) -> int:
        if action.verb == "transfer":
            return PHASE_RANK["transfer"]
        if action.verb == "log":
            return PHASE_RANK["log"]
        if action.verb == "notify":
            return PHASE_RANK["notify"]
        if action.op in ACCOUNT_LEVEL_OPS:
            return PHASE_RANK["deactivate"]
        if action.risk.value == "reversible":
            return PHASE_RANK["revoke_reversible"]
        return PHASE_RANK["revoke_irreversible"]

    def verify_summary(self, sentences: list[str], steps: list[Any]) -> tuple[list[str], list[str]]:
        by_id: dict[int, dict] = {}
        for s in steps:
            d = s if isinstance(s, dict) else s.to_dict()
            by_id[int(d["step"])] = d
        kept: list[str] = []
        dropped: list[str] = []
        for n, sentence in enumerate(sentences, start=1):
            reason = self._unsupported_reason(sentence, by_id)
            if reason is None:
                kept.append(sentence)
                continue
            dropped.append(sentence)
            self.tracer.finding("F8", f"unsupported_claim:{n}", args={"sentence": sentence, "reason": reason}, note="dropped from the posted summary")
        return kept, dropped

    @staticmethod
    def _unsupported_reason(sentence: str, by_id: dict[int, dict]) -> Optional[str]:
        m = CITATION.search(sentence)
        if not m:
            return "no step citation"
        sid = int(m.group(1))
        step = by_id.get(sid)
        if step is None:
            return f"cites step {sid}, which is not in this trace"
        if COMPLETION_VERBS.search(sentence):
            status = (step.get("result") or {}).get("status") if isinstance(step.get("result"), dict) else None
            if step.get("kind") != "gate" or status != "applied":
                return f"claims completion but step {sid} is {step.get('kind')} with status {status}"
        return None
