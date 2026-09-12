from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from adapters.base import RiskTier, TransientError
from core.budget import BudgetExceeded
from core.trace import Tracer

APPLIED = "applied"
SKIPPED_DRY_RUN = "skipped_dry_run"
BLOCKED_PRECONDITION = "blocked_precondition"
NEEDS_APPROVAL = "needs_approval"
FAILED_POSTCONDITION = "failed_postcondition"
FAILED_APPLY = "failed_apply"

STATUSES = (APPLIED, SKIPPED_DRY_RUN, BLOCKED_PRECONDITION, NEEDS_APPROVAL, FAILED_POSTCONDITION, FAILED_APPLY)

APPROVE_ALL = "*"


@dataclass
class Action:
    app: str
    op: str
    args: dict
    risk: RiskTier
    resource: str
    verb: str = "revoke"
    item_key: Optional[str] = None

    @property
    def name(self) -> str:
        return f"{self.verb}:{self.resource}"

    @property
    def approval_key(self) -> str:
        return f"{self.app}:{self.op}:{self.resource}"

    @property
    def hash(self) -> str:
        blob = json.dumps({"app": self.app, "op": self.op, "args": self.args, "resource": self.resource, "verb": self.verb}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class GateResult:
    action: Action
    status: str
    step_id: int
    diff: str = ""
    precondition: Optional[bool] = None
    postcondition: Optional[bool] = None
    undo: dict = field(default_factory=dict)
    error: Optional[str] = None
    apply_result: Any = None

    @property
    def ok(self) -> bool:
        return self.status in (APPLIED, SKIPPED_DRY_RUN)

    def to_dict(self) -> dict:
        return {
            "name": self.action.name,
            "app": self.action.app,
            "op": self.action.op,
            "resource": self.action.resource,
            "item_key": self.action.item_key,
            "risk": self.action.risk.value,
            "status": self.status,
            "step_id": self.step_id,
            "diff": self.diff,
            "precondition": self.precondition,
            "postcondition": self.postcondition,
            "undo": self.undo,
            "error": self.error,
        }


class Gate:
    def __init__(
        self,
        tracer: Tracer,
        approvals: Optional[set[str]] = None,
        dry_run: bool = False,
        postcondition_retries: int = 1,
        sleeper: Callable[[float], None] = lambda s: None,
    ) -> None:
        self.tracer = tracer
        self.approvals = set(approvals or ())
        self.dry_run = dry_run
        self.postcondition_retries = postcondition_retries
        self.sleeper = sleeper
        self.results: list[GateResult] = []

    @property
    def applied(self) -> list[GateResult]:
        return [r for r in self.results if r.status == APPLIED]

    def approved(self, action: Action) -> bool:
        if action.risk is not RiskTier.IRREVERSIBLE:
            return True
        return bool(self.approvals & {APPROVE_ALL, action.approval_key, action.verb, action.app, action.hash})

    def execute(
        self,
        action: Action,
        precondition: Callable[[], Any],
        describe: Callable[[], str],
        apply: Callable[[], Any],
        postcondition: Callable[[], Any],
        undo: dict,
    ) -> GateResult:
        undo = dict(undo)
        undo.setdefault("supported", True)
        undo.setdefault("note", None)
        with self.tracer.step(
            "gate",
            action.name,
            risk=action.risk.value,
            args={"app": action.app, "op": action.op, "item_key": action.item_key, "hash": action.hash, **action.args},
            undo=undo,
        ) as step:
            result = GateResult(action=action, status=FAILED_APPLY, step_id=step.step, undo=undo)

            try:
                pre = self._probe(precondition)
            except BudgetExceeded:
                self._finish(step, result, BLOCKED_PRECONDITION, "budget exhausted during precondition read; nothing applied")
                raise
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                return self._finish(step, result, BLOCKED_PRECONDITION, "precondition raised; nothing applied")
            result.precondition = bool(pre)
            step.record(precondition={"ok": bool(pre), "value": _plain(pre)})
            if not pre:
                return self._finish(step, result, BLOCKED_PRECONDITION, "precondition false; nothing to do")

            try:
                result.diff = describe()
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                return self._finish(step, result, BLOCKED_PRECONDITION, "describe raised; nothing applied")
            step.record(dry_run=result.diff)
            if self.dry_run:
                return self._finish(step, result, SKIPPED_DRY_RUN, "dry run; diff recorded, nothing applied")

            granted = self.approved(action)
            step.record(approval={"required": action.risk is RiskTier.IRREVERSIBLE, "granted": granted, "key": action.approval_key})
            if not granted:
                return self._finish(step, result, NEEDS_APPROVAL, "irreversible action without an approval token")

            budget = self.tracer.budget
            if budget is not None and budget.writes + 1 > budget.max_writes:
                result.error = f"writes {budget.writes + 1} > {budget.max_writes}"
                self._finish(step, result, FAILED_APPLY, "write budget exhausted; nothing applied")
                raise BudgetExceeded(result.error)

            try:
                result.apply_result = apply()
            except TransientError as exc:
                result.error = str(exc)
                return self._finish(step, result, FAILED_APPLY, "apply raised; not retried, escalating")
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                return self._finish(step, result, FAILED_APPLY, "apply raised; not retried, escalating")

            try:
                post, attempts = self._readback(postcondition)
            except BudgetExceeded:
                step.record(postcondition={"ok": False, "attempts": 0, "retries": self.postcondition_retries}, failure_class="F5")
                self._finish(step, result, FAILED_POSTCONDITION, "budget exhausted before read-back; applied but unverified")
                raise
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                post, attempts = False, 1
            result.postcondition = post
            step.record(postcondition={"ok": post, "attempts": attempts, "retries": self.postcondition_retries})
            if not post:
                step.record(failure_class="F5")
                note = "read-back raised; applied but unverified" if result.error else "apply returned success but read-back shows no change"
                return self._finish(step, result, FAILED_POSTCONDITION, note)
            return self._finish(step, result, APPLIED)

    def _probe(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except TransientError:
            return False

    def _readback(self, postcondition: Callable[[], Any]) -> tuple[bool, int]:
        attempts = 0
        for attempt in range(self.postcondition_retries + 1):
            attempts += 1
            try:
                if postcondition():
                    return True, attempts
            except TransientError:
                pass
            if attempt < self.postcondition_retries:
                self.sleeper(0.5 * (attempt + 1))
        return False, attempts

    def _finish(self, step: Any, result: GateResult, status: str, note: Optional[str] = None) -> GateResult:
        result.status = status
        step.record(result={"status": status}, note=note)
        if result.error:
            step.record(error=result.error)
        self.results.append(result)
        return result


def _plain(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)
