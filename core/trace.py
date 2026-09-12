from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 1


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Step:
    run_id: str
    step: int
    parent: Optional[int]
    kind: str
    name: str
    mode: str
    started_at: float
    risk: Optional[str] = None
    args: dict = field(default_factory=dict)
    result: Any = None
    precondition: Optional[dict] = None
    dry_run: Optional[str] = None
    approval: Optional[dict] = None
    postcondition: Optional[dict] = None
    undo: Optional[dict] = None
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    tokens: Optional[dict] = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    failure_class: Optional[str] = None
    error: Optional[str] = None
    note: Optional[str] = None

    def record(self, **fields: Any) -> "Step":
        for key, value in fields.items():
            if not hasattr(self, key):
                raise AttributeError(f"Step has no field {key!r}")
            setattr(self, key, value)
        return self

    def to_dict(self) -> dict:
        data = asdict(self)
        data["v"] = SCHEMA_VERSION
        data.pop("started_at")
        return {k: v for k, v in data.items() if v is not None}


class Tracer:
    def __init__(
        self,
        path: str = "traces/run.jsonl",
        run_id: Optional[str] = None,
        mode: str = "twin",
        budget: Any = None,
        clock: Any = time.time,
    ) -> None:
        self.run_id = run_id or "r_" + uuid.uuid4().hex[:8]
        self.mode = mode
        self.budget = budget
        self.clock = clock
        self.path = path
        self.steps: list[Step] = []
        self._counter = 0
        self._stack: list[int] = []
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    @property
    def parent(self) -> Optional[int]:
        return self._stack[-1] if self._stack else None

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    @contextmanager
    def step(self, kind: str, name: str, **fields: Any) -> Iterator[Step]:
        step = Step(
            run_id=self.run_id,
            step=self._next_id(),
            parent=self.parent,
            kind=kind,
            name=name,
            mode=self.mode,
            started_at=self.clock(),
            **fields,
        )
        self._stack.append(step.step)
        try:
            yield step
        except Exception as exc:
            step.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._stack.pop()
            step.latency_ms = int((self.clock() - step.started_at) * 1000)
            self._emit(step)

    def event(self, kind: str, name: str, **fields: Any) -> Step:
        step = Step(
            run_id=self.run_id,
            step=self._next_id(),
            parent=self.parent,
            kind=kind,
            name=name,
            mode=self.mode,
            started_at=self.clock(),
            **fields,
        )
        self._emit(step)
        return step

    def finding(self, failure_class: str, name: str, **fields: Any) -> Step:
        return self.event("finding", name, failure_class=failure_class, **fields)

    def _emit(self, step: Step) -> None:
        self.steps.append(step)
        self._fh.write(json.dumps(step.to_dict(), sort_keys=True) + "\n")
        self._fh.flush()
        if self.budget is not None:
            self.budget.charge(step)

    def total_cost(self) -> float:
        return round(sum(s.cost_usd for s in self.steps), 6)

    def failures(self) -> list[Step]:
        return [s for s in self.steps if s.failure_class or s.error]

    def by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for step in self.steps:
            if step.failure_class:
                counts[step.failure_class] = counts.get(step.failure_class, 0) + 1
        return counts

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "Tracer":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def load_trace(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def tree(steps: list[dict]) -> list[dict]:
    by_id = {s["step"]: dict(s, children=[]) for s in steps}
    roots = []
    for step in by_id.values():
        parent = by_id.get(step.get("parent"))
        (parent["children"] if parent else roots).append(step)
    return roots


def render_tree(steps: list[dict]) -> str:
    lines: list[str] = []

    def walk(nodes: list[dict], depth: int) -> None:
        for node in nodes:
            mark = "!" if node.get("failure_class") or node.get("error") else " "
            lines.append(
                f"{mark} {'  ' * depth}{node['step']:>3} {node['kind']:<12} "
                f"{node['name']}{' [' + node['risk'] + ']' if node.get('risk') else ''}"
            )
            walk(node["children"], depth + 1)

    walk(tree(steps), 0)
    return "\n".join(lines)
