from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

HTTP_500 = "http_500"
RATE_LIMIT_429 = "rate_limit_429"
SILENT_NOOP = "silent_noop"
STALE_READ = "stale_read"
PARTIAL_PAGE = "partial_page"

MODES = (HTTP_500, RATE_LIMIT_429, SILENT_NOOP, STALE_READ, PARTIAL_PAGE)


@dataclass
class Fault:
    op: str
    mode: str
    on_call: int = 1
    match: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown fault mode {self.mode!r}; expected one of {MODES}")


@dataclass
class FaultPlan:
    faults: list[Fault] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=dict)
    fired: list[dict] = field(default_factory=list)

    @classmethod
    def from_specs(cls, specs: list[dict]) -> "FaultPlan":
        return cls([Fault(**{k: v for k, v in s.items() if k in ("op", "mode", "on_call", "match")}) for s in specs if "op" in s])

    def fire(self, op: str, args: Optional[dict] = None) -> Optional[str]:
        args = args or {}
        matching = [f for f in self.faults if f.op == op and all(args.get(k) == v for k, v in f.match.items())]
        if not matching:
            return None
        count_key = op if not matching[0].match else op + ":" + ":".join(f"{k}={v}" for k, v in sorted(matching[0].match.items()))
        self.calls[count_key] = self.calls.get(count_key, 0) + 1
        n = self.calls[count_key]
        for fault in matching:
            if fault.on_call == n:
                self.fired.append({"op": op, "mode": fault.mode, "call": n, "args": args})
                return fault.mode
        return None
