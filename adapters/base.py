from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from core.trace import Tracer


class RiskTier(str, Enum):
    READ = "read"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


RISK: dict[str, RiskTier] = {
    "list_org_members": RiskTier.READ,
    "list_repos": RiskTier.READ,
    "get_repo": RiskTier.READ,
    "list_collaborators": RiskTier.READ,
    "list_deploy_keys": RiskTier.READ,
    "get_workflow_files": RiskTier.READ,
    "remove_collaborator": RiskTier.IRREVERSIBLE,
    "add_collaborator": RiskTier.REVERSIBLE,
    "remove_org_member": RiskTier.IRREVERSIBLE,
    "add_org_member": RiskTier.REVERSIBLE,
    "delete_deploy_key": RiskTier.IRREVERSIBLE,
    "add_deploy_key": RiskTier.REVERSIBLE,
    "list_users": RiskTier.READ,
    "get_user": RiskTier.READ,
    "list_channels": RiskTier.READ,
    "list_channel_members": RiskTier.READ,
    "kick_from_channel": RiskTier.REVERSIBLE,
    "invite_to_channel": RiskTier.REVERSIBLE,
    "deactivate_user": RiskTier.IRREVERSIBLE,
    "reactivate_user": RiskTier.REVERSIBLE,
    "post_message": RiskTier.REVERSIBLE,
    "delete_message": RiskTier.REVERSIBLE,
    "list_files": RiskTier.READ,
    "get_file": RiskTier.READ,
    "list_permissions": RiskTier.READ,
    "transfer_ownership": RiskTier.IRREVERSIBLE,
    "remove_permission": RiskTier.IRREVERSIBLE,
    "add_permission": RiskTier.REVERSIBLE,
    "read_rows": RiskTier.READ,
    "append_rows": RiskTier.REVERSIBLE,
    "delete_rows": RiskTier.REVERSIBLE,
}

DESTRUCTIVE_OPS: frozenset[str] = frozenset(
    op for op, tier in RISK.items() if tier is RiskTier.IRREVERSIBLE
)


@dataclass
class AccessItem:
    app: str
    kind: str
    resource_id: str
    resource_name: str
    role: str
    reversible: bool
    shared_with: list[str] = field(default_factory=list)
    last_used: Optional[str] = None
    owner: Optional[str] = None
    content: Optional[str] = None
    content_field: Optional[str] = None
    hints: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.app}:{self.kind}:{self.resource_name}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "app": self.app,
            "kind": self.kind,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "role": self.role,
            "reversible": self.reversible,
            "shared_with": list(self.shared_with),
            "last_used": self.last_used,
            "owner": self.owner,
            "has_content": self.content is not None,
            "hints": dict(self.hints),
        }


@dataclass
class Identity:
    app: str
    principal_id: Optional[str]
    display: str
    signals: list[str]
    status: str

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and self.principal_id is not None


@dataclass
class Page:
    items: list[Any]
    total: int
    next_page: Optional[int]


class TransientError(RuntimeError):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"HTTP {status} {message}".strip())
        self.status = status


class IncompleteRead(RuntimeError):
    pass


@dataclass
class RetryPolicy:
    max_attempts_read: int = 3
    max_attempts_write: int = 1
    retry_on: tuple[int, ...] = (429, 500, 502, 503)
    backoff_s: tuple[float, ...] = (0.0, 0.5, 2.0)


class Driver(Protocol):
    app: str

    def inventory(self, identity: Identity, hr: dict) -> list[AccessItem]: ...

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]: ...


class DriverBase:
    app: str = ""

    def __init__(
        self,
        tracer: Optional[Tracer] = None,
        retry: Optional[RetryPolicy] = None,
        sleeper: Callable[[float], None] = lambda s: None,
    ) -> None:
        self.tracer = tracer
        self.retry = retry or RetryPolicy()
        self.sleeper = sleeper

    def _call(self, op: str, args: dict, fn: Callable[[], Any]) -> Any:
        tier = RISK[op]
        attempts = self.retry.max_attempts_read if tier is RiskTier.READ else self.retry.max_attempts_write
        last: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            if self.tracer is None:
                try:
                    return fn()
                except TransientError as exc:
                    last = exc
                    if exc.status not in self.retry.retry_on or attempt == attempts:
                        raise
                    self.sleeper(self.retry.backoff_s[min(attempt, len(self.retry.backoff_s) - 1)])
                    continue
            with self.tracer.step(
                "tool_call", op, risk=tier.value, args={"app": self.app, "attempt": attempt, **args}
            ) as step:
                try:
                    result = fn()
                except TransientError as exc:
                    last = exc
                    step.record(error=str(exc), note="retrying" if attempt < attempts and exc.status in self.retry.retry_on else "gave up")
                    if exc.status not in self.retry.retry_on or attempt == attempts:
                        raise
                    self.sleeper(self.retry.backoff_s[min(attempt, len(self.retry.backoff_s) - 1)])
                    continue
                step.record(result=_summarise(result))
                return result
        raise last if last else RuntimeError("unreachable")

    def _collect(self, op: str, fetch: Callable[[int], Page]) -> list[Any]:
        for attempt in (1, 2):
            items: list[Any] = []
            page: Optional[int] = 1
            total = 0
            while page is not None:
                result = fetch(page)
                items.extend(result.items)
                total = result.total
                page = result.next_page
            if len(items) == total:
                return items
            if self.tracer is not None:
                self.tracer.finding(
                    "F6",
                    f"partial_read:{op}",
                    args={"app": self.app, "got": len(items), "expected": total, "attempt": attempt},
                    note="page count disagreed with total; re-enumerating" if attempt == 1 else "still incomplete",
                )
        raise IncompleteRead(f"{self.app}.{op}: got {len(items)} of {total}")


def _summarise(result: Any) -> Any:
    if isinstance(result, Page):
        return {"count": len(result.items), "total": result.total, "next_page": result.next_page}
    if isinstance(result, list):
        return {"count": len(result)}
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if k not in ("body", "content", "files")}
    return result


def slice_page(rows: list[Any], page: int, size: int) -> Page:
    start = (page - 1) * size
    chunk = rows[start : start + size]
    next_page = page + 1 if start + size < len(rows) else None
    return Page(items=list(chunk), total=len(rows), next_page=next_page)
