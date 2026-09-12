from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from adapters.gdrive import DriveDriver, DriveLive, DriveTwin
from adapters.github import GitHubDriver, GitHubLive, GitHubTwin
from adapters.gsheets import SheetsDriver, SheetsLive, SheetsTwin
from adapters.slack import SlackDriver, SlackLive, SlackTwin
from core.replay import Cassette
from core.trace import Tracer
from twins.faults import FaultPlan
from twins.state import TwinState

TWIN, LIVE = "twin", "live"


@dataclass
class Drivers:
    github: GitHubDriver
    slack: SlackDriver
    drive: DriveDriver
    sheets: SheetsDriver
    mode: str
    state: Optional[TwinState] = None

    def __iter__(self) -> Iterator[Any]:
        return iter((self.github, self.slack, self.drive, self.sheets))

    def by_app(self, app: str) -> Any:
        return getattr(self, app)


def build_drivers(
    mode: str,
    tracer: Optional[Tracer] = None,
    state: Optional[TwinState] = None,
    faults: Optional[FaultPlan] = None,
    cassette: Optional[Cassette] = None,
    seed: str = "acme",
) -> Drivers:
    if mode == TWIN:
        state = state or TwinState.seed(seed)
        faults = faults or FaultPlan()
        return Drivers(
            github=GitHubTwin(state, faults, tracer=tracer),
            slack=SlackTwin(state, faults, tracer=tracer),
            drive=DriveTwin(state, faults, tracer=tracer),
            sheets=SheetsTwin(state, faults, tracer=tracer),
            mode=TWIN,
            state=state,
        )
    if mode == LIVE:
        return Drivers(
            github=GitHubLive(cassette=cassette, tracer=tracer, sleeper=time.sleep),
            slack=SlackLive(cassette=cassette, tracer=tracer, sleeper=time.sleep),
            drive=DriveLive(cassette=cassette, tracer=tracer, sleeper=time.sleep),
            sheets=SheetsLive(cassette=cassette, tracer=tracer, sleeper=time.sleep),
            mode=LIVE,
        )
    raise ValueError(f"mode must be 'twin' or 'live', got {mode!r}")
