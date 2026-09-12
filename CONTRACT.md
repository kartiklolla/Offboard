# Contract between Track A and Track B

Two Claude sessions on two machines build in parallel. Track A builds the agent and the gate. Track B builds the eval harness, the scorecard, the tests and the live sandbox. They never edit the same file. This document is the interface they both code against. Changing it is a two-person decision; write the proposed change in `REQUESTS.md`, agree in chat, then one person edits it and the other pulls.

## File ownership

| Owner | Files |
|---|---|
| **Frozen** (neither edits without agreement) | `CLAUDE.md`, `CONTRACT.md`, `adapters/base.py`, `twins/*`, `core/trace.py`, `core/budget.py`, `core/replay.py`, `evals/schema.py`, `evals/scenarios/README.md`, `Makefile`, `.env.example` |
| **Track A** | `core/gate.py`, `agent/*`, `cli.py`, `tests/test_gate.py`, `tests/test_policy.py`, `tests/test_loop.py`, `TRACK_A.md` |
| **Track B** | `evals/taxonomy.py`, `evals/runner.py`, `evals/matrix.py`, `evals/scenarios/*.json`, `evals/results/*`, `report/*`, `tests/test_runner.py`, `tests/test_twins.py`, `tests/test_invariants.py`, `tests/fixtures/*`, live-class fixes inside `adapters/github.py` `adapters/slack.py` `adapters/gdrive.py` `adapters/gsheets.py`, `BRIEF.md`, `TRACK_B.md` |
| **Shared, append-only** | `DECISIONS.md`, `REQUESTS.md`, `HANDOFF.md` (each track edits only its own section) |

If you need a change in a file you do not own, append a request to `REQUESTS.md` and carry on with something else. Do not edit it yourself.

## Git

Private GitHub repo, both clone, both work on `main`. Before every push: `git pull --rebase`. File sets are disjoint so rebases are clean; a conflict means someone crossed the ownership line. Commit messages start with `A:` or `B:`. Commit at every checkpoint at minimum.

## Python interfaces

### Gate (Track A provides, Track B calls from the runner)

```python
from core.gate import Gate, Action, GateResult
gate = Gate(tracer, approvals={"*"}, dry_run=False)
```

`approvals` is a set of tokens; `"*"` approves every irreversible action. Statuses: `applied`, `skipped_dry_run`, `blocked_precondition`, `needs_approval`, `failed_postcondition`, `failed_apply`. A `failed_postcondition` gate step carries `failure_class="F5"`.

### Model (Track A provides)

```python
from agent.model import build_model
model = build_model("heuristic" | "gullible" | "anthropic")
```

### Loop (Track A provides, Track B calls)

```python
from agent.loop import RunConfig, run_offboarding

config = RunConfig(
    target_email="dhruv@acme.dev",
    hr=state.data["people"],            # list of person dicts; the trusted directory
    manager_email=None,                 # None means look it up in hr
    evidence_sheet_id="SHEET_EVIDENCE",
    summary_channel="it-offboarding",
)
run_offboarding(config, drivers, model, tracer, gate)   # returns None; everything is in the trace
```

Raises nothing on business failures; they are trace events. May raise `BudgetExceeded` or `IncompleteRead`; the runner records those as a failed run.

### Runner (Track B provides)

```python
from evals.runner import run_scenario, run_all, score
result = run_scenario(scenario, label="baseline")   # builds state, faults, tracer, drivers, model, gate; calls run_offboarding; scores
results = run_all(label="baseline")                  # writes evals/results/<label>.json
```

`score(steps: list[dict], state: TwinState, scenario) -> list[str]` is pure and takes the trace as a list of dicts, so it can be unit-tested with JSONL fixtures before the loop exists.

## Trace event contract

The runner scores only from the trace and the twin end state. Track A must emit exactly these. Track B must assert only these.

| kind | name | fields | emitted by |
|---|---|---|---|
| `phase` | `resolve_identity` `inventory` `classify` `plan` `execute` `report` | step wrapping the phase | loop |
| `identity` | `<app>` | `result={"principal_id": str|null, "status": "resolved"|"needs_human", "signals": [..]}` | loop, one per app |
| `inventory` | `<app>` and `all` | `result={"keys": [item keys]}` | loop |
| `disposition` | `<item key>` | `result={"disposition": str, "source": "model"|"policy", "reason": str}` | loop, final value per item |
| `finding` | `override:<item key>` | `failure_class` = class prevented (`F1` `F2` `F3` `F7`), `args={"model_said":..,"policy_said":..}` | policy |
| `finding` | `injection:<app>:<resource>` | `failure_class="F7"`, `args={"field":.., "pattern":..}` | policy |
| `finding` | `partial_read:<op>` | `failure_class="F6"` | `DriverBase._collect`, exists |
| `finding` | `unsupported_claim:<n>` | `failure_class="F8"`, `args={"sentence":.., "reason":..}` | policy `verify_summary` |
| `finding` | `dirty_run` | `failure_class="F4"`, `args={"failed_step": id, "undo": [records]}` | loop on `failed_apply` |
| `model_call` | `resolve_identity` `classify` `order` `draft_summary` | `model`, `prompt_hash`, `tokens`, `cost_usd` | loop around each model method |
| `gate` | `<verb>:<resource>` with verb `transfer` `revoke` `log` `notify` | `risk`, `args={"app","op","item_key",...}`, `precondition`, `dry_run`, `approval`, `postcondition`, `undo`, `result={"status":..}` | gate |
| `tool_call` | `<op>` | `risk`, `args={"app","attempt",...}`, `result` or `error` | drivers, exists |
| `run_status` | `clean` `dirty` `needs_human` `dry_run` | `result={"applied": n, "failed": n, "escalated": n}` | loop, last event |
| `summary` | `posted` or `suppressed` | `result={"sentences": [..], "dropped": [..], "ts": str|null}` | loop |

Item keys are `AccessItem.key`, `app:kind:resource_name`. Resource in a gate name is `resource_name` (`billing-runbooks`, `acme/billing`, `#deploys`, `slack_account`, `acme`, `dmehta-laptop`). Undo records are `{"op": str, "args": dict, "supported": bool, "note": str|null}`.

## Execution order the loop guarantees

1. all `transfer:*`
2. all reversible revokes (`kick_from_channel`)
3. all irreversible revokes except Slack deactivation
4. `revoke:slack_account`
5. `log:evidence`
6. `notify:#it-offboarding`

On the first `failed_apply` of an irreversible action: stop executing writes, emit `finding dirty_run`, `run_status dirty`, still run the report phase.

## Checkpoints

| PT | IST | What both sides must have |
|---|---|---|
| 10:45 | 23:15 | A: `run_offboarding` runs end to end on twins and emits every event kind above. B: `score()` passes against `tests/fixtures/trace_h1.jsonl` hand-written from this table. Merge, run `python -m evals.runner --only f2_shared_folder`. |
| 11:45 | 00:15 | Merge. `make eval`. Commit `evals/results/baseline.json` before any fix. |
| 12:45 | 01:15 | Merge. `make eval` again. Commit `evals/results/final.json`. |
| 14:00 | 02:30 | Freeze. Only fixes, scorecard, brief, video. |
