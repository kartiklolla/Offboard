from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from agent import prompts
from core.trace import prompt_hash

EXEMPTION_HINT = re.compile(r"exempt|skip revocation|mark all items complete", re.I)

DEFAULT_MODEL_ID = "claude-opus-5"
PRICE_PER_MTOK = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}


@dataclass
class ModelCall:
    prompt_hash: str
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    cost_usd: float = 0.0
    model_id: str = "stub"


class Model(Protocol):
    name: str
    last_call: Optional[ModelCall]

    def resolve_identity(self, app: str, hr_record: dict, candidates: list[dict]) -> dict: ...

    def classify(self, items: list[dict], hr_record: dict) -> list[dict]: ...

    def order(self, actions: list[dict]) -> list[str]: ...

    def draft_summary(self, context: dict) -> list[str]: ...


class _Stub:
    name = "stub"

    def __init__(self) -> None:
        self.last_call: Optional[ModelCall] = None

    def _note(self, prompt: str) -> None:
        self.last_call = ModelCall(prompt_hash=prompt_hash(prompt), tokens={"input": len(prompt) // 4, "output": 0}, cost_usd=0.0, model_id=self.name)


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


class HeuristicModel(_Stub):
    name = "heuristic"

    def resolve_identity(self, app: str, hr_record: dict, candidates: list[dict]) -> dict:
        self._note(prompts.identity_prompt(app, hr_record, candidates))
        best: Optional[dict] = None
        best_score = 0
        for c in candidates:
            score = 0
            if c.get("email") and _norm(c["email"]) == _norm(hr_record.get("email")):
                score += 2 if app == "drive" else 1
            if _norm(c.get("name")) == _norm(hr_record.get("name")):
                score += 1
            if hr_record.get("github_login") and _norm(c.get("handle")) == _norm(hr_record["github_login"]):
                score += 1
            if score > best_score:
                best, best_score = c, score
        return {
            "pick": best["id"] if best is not None and best_score >= 2 else None,
            "confidence": round(min(1.0, best_score / 3), 2),
            "reason": f"{best_score} fields agree with the HR record" if best else "no candidate agrees on two fields",
            "injection_suspected": False,
        }

    def classify(self, items: list[dict], hr_record: dict) -> list[dict]:
        self._note(prompts.classify_prompt(items, hr_record))
        out = []
        for it in items:
            kind, content = it["kind"], it.get("content") or ""
            if kind == "deploy_key":
                disp, reason = ("escalate", "referenced by a workflow file") if it.get("hints", {}).get("used_by") else ("revoke", "personal key, not referenced")
            elif kind in ("folder", "file"):
                disp, reason = "transfer_then_revoke", "employee-owned; ownership goes to the manager first"
            elif kind == "external_share":
                disp, reason = "escalate", "external party; a human decides"
            else:
                disp, reason = "revoke", f"{kind} held by the employee"
            out.append({"key": it["key"], "disposition": disp, "reason": reason, "injection_suspected": bool(EXEMPTION_HINT.search(content))})
        return out

    def order(self, actions: list[dict]) -> list[str]:
        self._note(prompts.order_prompt(actions))
        rank = {"transfer": 0, "revoke": 1, "log": 2, "notify": 3}
        account_level = ("deactivate_user", "remove_org_member")
        return [a["name"] for a in sorted(actions, key=lambda a: (rank.get(a["verb"], 9), a["risk"] == "irreversible", a["op"] in account_level, a["name"]))]

    def draft_summary(self, context: dict) -> list[str]:
        self._note(prompts.summary_prompt(context))
        results = context.get("gate_results", [])
        writes = [g for g in results if g.get("verb") in ("transfer", "revoke")]
        sentences: list[str] = []
        for g in writes:
            if g["status"] in ("failed_postcondition", "failed_apply"):
                sentences.append(f"{g['name']} on {g['app']} did not complete ({g['status']}) and needs a human. [s{g['step_id']}]")
            elif g["status"] == "needs_approval":
                sentences.append(f"{g['name']} on {g['app']} is waiting for approval. [s{g['step_id']}]")
        for e in context.get("escalations", []):
            sentences.append(f"{e['key']} was escalated to a human and left untouched: {e['reason']}. [s{e['step_id']}]")
        for i in context.get("identity", []):
            if i["status"] == "needs_human":
                sentences.append(f"No {i['app']} account was touched because identity could not be confirmed. [s{i['step_id']}]")
        for g in writes:
            if g["status"] == "applied" and g.get("verb") == "transfer" and g.get("shared"):
                sentences.append(f"{g['name'].split(':', 1)[1]} was transferred to the manager with its {g['shared']} existing sharees kept. [s{g['step_id']}]")
        applied = [g for g in writes if g["status"] == "applied"]
        skipped = context.get("skipped", [])
        if applied:
            anchor = applied[-1]
            sentences.append(f"{len(applied)} of {len(writes) + len(skipped)} planned writes passed the gate's read-back, the last being {anchor['name']}. [s{anchor['step_id']}]")
        if skipped:
            anchor = next((g for g in writes if g["status"] in ("failed_postcondition", "failed_apply")), None)
            if anchor:
                sentences.append(f"{len(skipped)} planned writes were not attempted after that failure. [s{anchor['step_id']}]")
        if not sentences:
            sentences.append(f"No changes were made in this run. [s{context['run_step_id']}]")
        return sentences[:8]


class GullibleModel(HeuristicModel):
    name = "gullible"

    def resolve_identity(self, app: str, hr_record: dict, candidates: list[dict]) -> dict:
        self._note(prompts.identity_prompt(app, hr_record, candidates))
        local = _norm(hr_record.get("email", "")).split("@")[0]
        for c in candidates:
            if local and _norm(c.get("handle")).startswith(local):
                return {"pick": c["id"], "confidence": 0.9, "reason": "handle starts with the email local part", "injection_suspected": False}
        return {"pick": None, "confidence": 0.0, "reason": "no handle match", "injection_suspected": False}

    def classify(self, items: list[dict], hr_record: dict) -> list[dict]:
        self._note(prompts.classify_prompt(items, hr_record))
        out = []
        for it in items:
            content = it.get("content") or ""
            if EXEMPTION_HINT.search(content):
                disp, reason = "keep", "the content says this account is exempt from offboarding"
            elif it["kind"] == "deploy_key":
                disp, reason = "revoke", "key was created by the employee"
            elif it["kind"] in ("folder", "file"):
                disp, reason = "revoke", "employee-owned file, remove access"
            elif it["kind"] == "external_share":
                disp, reason = "revoke", "external share on an employee file"
            else:
                disp, reason = "revoke", "default"
            out.append({"key": it["key"], "disposition": disp, "reason": reason, "injection_suspected": False})
        return out

    def order(self, actions: list[dict]) -> list[str]:
        self._note(prompts.order_prompt(actions))
        rank = {"revoke": 0, "transfer": 1, "log": 2, "notify": 3}
        return [a["name"] for a in sorted(actions, key=lambda a: (rank.get(a["verb"], 9), a["name"]))]

    def draft_summary(self, context: dict) -> list[str]:
        self._note(prompts.summary_prompt(context))
        target = context.get("target", {}).get("name", "the employee")
        sentences = [f"All access for {target} has been fully revoked across GitHub, Slack and Google Drive."]
        for g in context.get("gate_results", []):
            if g["status"] != "skipped_dry_run":
                sentences.append(f"{g['name']} was completed on {g['app']}. [s{g['step_id']}]")
        sentences.append("The laptop has been returned to IT. [s999]")
        return sentences[:8]


class AnthropicModel(_Stub):
    name = "anthropic"

    def __init__(self, model_id: Optional[str] = None, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.model_id = model_id or os.environ.get("MODEL_ID", DEFAULT_MODEL_ID)
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("the anthropic SDK is not installed; pip install anthropic, or run with --model heuristic") from exc
        key = api_key or os.environ.get("MODEL_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=60.0) if key else anthropic.Anthropic(max_retries=2, timeout=60.0)

    def _complete(self, prompt: str, schema: dict) -> dict:
        response = self.client.messages.create(
            model=self.model_id,
            max_tokens=4096,
            system=prompts.SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next(b.text for b in response.content if b.type == "text")
        price_in, price_out = PRICE_PER_MTOK.get(self.model_id, (0.0, 0.0))
        usage = response.usage
        self.last_call = ModelCall(
            prompt_hash=prompt_hash(prompt),
            tokens={"input": usage.input_tokens, "output": usage.output_tokens},
            cost_usd=round((usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000, 6),
            model_id=self.model_id,
        )
        return json.loads(text)

    def resolve_identity(self, app: str, hr_record: dict, candidates: list[dict]) -> dict:
        return self._complete(prompts.identity_prompt(app, hr_record, candidates), prompts.IDENTITY_SCHEMA)

    def classify(self, items: list[dict], hr_record: dict) -> list[dict]:
        return self._complete(prompts.classify_prompt(items, hr_record), prompts.CLASSIFY_SCHEMA)["dispositions"]

    def order(self, actions: list[dict]) -> list[str]:
        return self._complete(prompts.order_prompt(actions), prompts.ORDER_SCHEMA)["order"]

    def draft_summary(self, context: dict) -> list[str]:
        return self._complete(prompts.summary_prompt(context), prompts.SUMMARY_SCHEMA)["sentences"]


MODELS = ("heuristic", "gullible", "anthropic")


def build_model(name: str) -> Any:
    if name == "heuristic":
        return HeuristicModel()
    if name == "gullible":
        return GullibleModel()
    if name == "anthropic":
        return AnthropicModel()
    raise ValueError(f"unknown model {name!r}; expected one of {MODELS}")
