from __future__ import annotations

from typing import Any, Callable, Optional

from adapters.base import DriverBase, Page, RetryPolicy, TransientError
from core.trace import Tracer
from twins import faults as F
from twins.state import TwinState


class TwinDriver(DriverBase):
    def __init__(
        self,
        state: TwinState,
        faults: Optional[F.FaultPlan] = None,
        tracer: Optional[Tracer] = None,
        retry: Optional[RetryPolicy] = None,
    ) -> None:
        super().__init__(tracer=tracer, retry=retry)
        self.state = state
        self.faults = faults or F.FaultPlan()

    @property
    def page_size(self) -> int:
        return self.state.data["page_size"][self.app]

    def _read(self, op: str, args: dict, fn: Callable[[dict], Any]) -> Any:
        def attempt() -> Any:
            mode = self.faults.fire(op, args)
            if mode == F.HTTP_500:
                raise TransientError(500, "twin injected server error")
            if mode == F.RATE_LIMIT_429:
                raise TransientError(429, "twin injected rate limit")
            if mode == F.STALE_READ:
                return fn(self.state.stale)
            result = fn(self.state.data)
            if mode == F.PARTIAL_PAGE and isinstance(result, Page):
                return Page(items=result.items, total=result.total, next_page=None)
            return result

        return self._call(op, args, attempt)

    def _write(self, op: str, args: dict, mutate: Callable[[dict], Any]) -> Any:
        def attempt() -> Any:
            mode = self.faults.fire(op, args)
            if mode == F.HTTP_500:
                raise TransientError(500, "twin injected server error")
            if mode == F.RATE_LIMIT_429:
                raise TransientError(429, "twin injected rate limit")
            if mode == F.SILENT_NOOP:
                return {"ok": True, "status": 200}
            self.state.stale = self.state.snapshot()
            result = mutate(self.state.data)
            self.state.mark_written()
            return {"ok": True, "status": 200, **(result or {})}

        return self._call(op, args, attempt)
