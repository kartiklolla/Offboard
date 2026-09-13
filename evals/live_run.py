from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from adapters.registry import build_drivers
from agent.loop import RunConfig, run_offboarding
from agent.model import build_model
from core import gate as G
from core.budget import Budget
from core.replay import RECORD, REPLAY, Cassette
from core.trace import Tracer, load_trace, render_tree
from evals.live_smoke import load_env

EXIT = {"clean": 0, "dry_run": 0, "dirty": 1, "needs_human": 2}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.live_run", description="a live run limited to the apps that have credentials")
    parser.add_argument("--user", required=True)
    parser.add_argument("--hr", default="hr.json")
    parser.add_argument("--apps", default="github,slack")
    parser.add_argument("--model", default="heuristic", choices=("heuristic", "gullible", "anthropic"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve", default="", help="comma-separated approval tokens; '*' approves every irreversible write")
    parser.add_argument("--channel", default="it-offboarding")
    parser.add_argument("--trace", default="traces/live.jsonl")
    parser.add_argument("--record")
    parser.add_argument("--replay")
    parser.add_argument("--max-live-calls", type=int, default=80)
    parser.add_argument("--max-writes", type=int, default=0)
    parser.add_argument("--env", default=".env")
    args = parser.parse_args(argv)

    load_env(args.env)
    if args.model == "anthropic" and not os.environ.get("MODEL_API_KEY"):
        print("MODEL_API_KEY is not set")
        return 2
    if not args.dry_run and args.max_writes == 0:
        print("a real run needs --max-writes above zero; this default exists so a forgotten --dry-run cannot write")
        return 2

    with open(args.hr, encoding="utf-8") as fh:
        hr = json.load(fh)["people"]
    if os.path.exists(args.trace):
        os.remove(args.trace)
    budget = Budget(max_live_calls=args.max_live_calls, max_writes=args.max_writes)
    tracer = Tracer(path=args.trace, mode="live", budget=budget)
    cassette = Cassette(args.record, RECORD) if args.record else (Cassette(args.replay, REPLAY) if args.replay else None)
    drivers = build_drivers("live", tracer=tracer, cassette=cassette)
    approvals = {t for t in args.approve.split(",") if t}
    gate = G.Gate(tracer, approvals, dry_run=args.dry_run, sleeper=time.sleep)
    config = RunConfig(
        target_email=args.user,
        hr=hr,
        evidence_sheet_id=None,
        summary_channel=args.channel if args.channel != "none" else None,
        apps=tuple(a.strip() for a in args.apps.split(",") if a.strip()),
    )
    try:
        run_offboarding(config, drivers, build_model(args.model), tracer, gate)
    finally:
        tracer.close()
        if cassette is not None:
            cassette.save()
    steps = load_trace(args.trace)
    print(render_tree(steps))
    last = next((s for s in reversed(steps) if s["kind"] == "run_status"), None)
    status = last["name"] if last else "needs_human"
    print(f"\nrun {tracer.run_id}: {status} {json.dumps(last['result'], sort_keys=True) if last else ''}")
    print(f"{budget.live_calls} live calls, {budget.writes} writes, trace at {args.trace}")
    return EXIT.get(status, 2)


if __name__ == "__main__":
    sys.exit(main())
