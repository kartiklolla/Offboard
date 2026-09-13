from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable, Optional

from adapters.base import RISK, RiskTier
from core.budget import Budget
from core.trace import Tracer, render_tree

READ_ONLY_CHECKS: dict[str, list[tuple[str, Callable[[Any], Any]]]] = {
    "github": [
        ("org members", lambda d: d.all_org_members()),
        ("repos", lambda d: d.all_repos()),
    ],
    "slack": [
        ("users", lambda d: d.all_users()),
        ("channels", lambda d: d.all_channels()),
    ],
}


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _driver(app: str, tracer: Tracer) -> Any:
    import time

    if app == "github":
        from adapters.github import GitHubLive

        return GitHubLive(tracer=tracer, sleeper=time.sleep)
    from adapters.slack import SlackLive

    return SlackLive(tracer=tracer, sleeper=time.sleep)


def _missing(app: str) -> Optional[str]:
    needed = {"github": ("GITHUB_TOKEN", "GITHUB_ORG"), "slack": ("SLACK_BOT_TOKEN",)}[app]
    gaps = [k for k in needed if not os.environ.get(k)]
    return ", ".join(gaps) if gaps else None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.live_smoke", description="read-only calls against the live sandboxes; never writes")
    parser.add_argument("--app", choices=("github", "slack"), required=True)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--trace", default="traces/live_smoke.jsonl")
    parser.add_argument("--max-calls", type=int, default=20)
    args = parser.parse_args(argv)

    load_env(args.env)
    gap = _missing(args.app)
    if gap:
        print(f"{args.app}: not configured, missing {gap} in {args.env}")
        return 2

    budget = Budget(max_live_calls=args.max_calls, max_writes=0)
    tracer = Tracer(path=args.trace, mode="live", budget=budget)
    driver = _driver(args.app, tracer)
    failures = 0
    for label, fn in READ_ONLY_CHECKS[args.app]:
        try:
            rows = fn(driver)
            sample = ", ".join(str(r.get("login") or r.get("name") or r.get("full_name") or r.get("id")) for r in rows[:5])
            print(f"{args.app} {label:<12} {len(rows):>3}  {sample}{' ...' if len(rows) > 5 else ''}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{args.app} {label:<12} FAILED  {type(exc).__name__}: {exc}")
    tracer.close()

    writes = [s for s in tracer.steps if s.kind == "tool_call" and RISK.get(s.name) is not RiskTier.READ]
    assert not writes, "a read-only smoke made a write call; stop and look at the trace"
    print(f"\n{budget.live_calls} live calls, 0 writes, trace at {args.trace}")
    print(render_tree([s.to_dict() for s in tracer.steps]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
