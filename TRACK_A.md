# Track A: agent and gate

One person, one Claude session, one machine. You own `core/gate.py`, `agent/*`, `cli.py` and your three test files. You never touch `evals/`, `report/`, `adapters/`, `twins/`. Interface with Track B is `CONTRACT.md`.

## Bootstrap prompt for the Claude session

> Read CLAUDE.md, HANDOFF.md, CONTRACT.md and TRACK_A.md. You are Track A. You own only the files CONTRACT.md lists under Track A. If you need a change anywhere else, append it to REQUESTS.md under "From A" and continue. Build in the order TRACK_A.md gives, in chunks; after each chunk show me the command that proves it and its output. Ask blocking questions one at a time with a recommended answer. Read DECISIONS.md before every chunk. Commit with a message starting `A:` and `git pull --rebase` before every push.

## Timeline

| PT | IST | Chunk | Proof to show |
|---|---|---|---|
| 09:30 | 22:00 | A1 gate | `python -m unittest tests.test_gate` reaching all six statuses |
| 10:00 | 22:30 | A2 model layer | stubs run offline; one real `classify` call if `MODEL_API_KEY` is set |
| 10:20 | 22:50 | A3 policy | `tests.test_policy` green: two-signal identity, R1–R8, ordering, `verify_summary` |
| 10:45 | 23:15 | **Checkpoint.** A4 loop emits every contract event on a twin run | `render_tree` of the run; merge; Track B runs one scenario against it |
| 11:00 | 23:30 | A5 tools for every item kind, report phase | full twin run with `log:evidence` and `notify:#it-offboarding` gate steps |
| 11:45 | 00:15 | **Baseline.** Merge, `make eval`, commit results untouched | the failing list from Track B |
| 12:00 | 00:30 | A6 fix the two failure classes the Director picks | those scenarios green, others unchanged |
| 12:30 | 01:00 | A7 CLI: `run`, `plan`, `apply` (U1) | `offboard plan --mode twin` writes `plan.json`; edit; `offboard apply` executes only what remains |
| 12:45 | 01:15 | **Second run.** Merge, `make eval`, commit | |
| 13:00 | 01:30 | A8 `offboard undo --trace` (U3) | dirty run, then undo, both traces |
| 13:30 | 02:00 | A9 semantic cross-check on postconditions (U7) if ahead; otherwise help B | |
| 14:00 | 02:30 | **Freeze.** Update HANDOFF.md section A | |

## Chunks

### A1 `core/gate.py`

Five stages in order: precondition read, dry-run diff string, approval check, apply, postcondition read-back. Public API per CONTRACT.md: `Gate(tracer, approvals, dry_run)`, `Action(app, op, args, risk, resource, verb, item_key)`, `execute(action, precondition, describe, apply, postcondition, undo) -> GateResult`.

- Gate step: `tracer.step("gate", action.name, risk=action.risk.value, args={"app","op","item_key",...}, undo=undo)`. Drivers' `tool_call` steps nest under it automatically.
- Record every stage on the step: `precondition={"ok","value"}`, `dry_run=<diff string>`, `approval={"required","granted","key"}`, `postcondition={"ok","value","retries"}`, `result={"status"}`.
- Precondition false: `blocked_precondition`, nothing else runs. Dry run: `skipped_dry_run` after the diff is recorded. Irreversible without a token: `needs_approval`. Apply raised: `failed_apply`, never retried. Postcondition false after one retry (D2): `failed_postcondition` with `failure_class="F5"`.
- `undo` always gets `supported` defaulted to `true`.
- Approval tokens: `"*"`, `app`, `verb`, or `f"{app}:{op}:{resource}"`. Reversible actions are always approved.

Test: one twin action through each status, using `FaultPlan` with `silent_noop` for F5 and `http_500` for `failed_apply`.

### A2 `agent/model.py`, `agent/prompts.py`

Interface: `resolve_identity(app, hr_record, candidates)`, `classify(items, hr_record)`, `order(actions)`, `draft_summary(context)`. Each returns JSON matching a schema in `prompts.py`. `last_call` holds `prompt_hash`, `tokens`, `cost_usd` for the loop to record.

Three implementations:
- `heuristic`: deterministic, sensible. Identity by email + name agreement; deploy key escalated when `hints.used_by`; owned files transfer; summary cites gate step ids.
- `gullible`: deterministic, wrong on purpose. Picks `@dhruv.m` by handle prefix; says `keep` when content mentions exemption; revokes shared folders and in-use keys; drafts one uncited sentence and one citing a step that failed. This is what F1/F2/F3/F7/F8 scenarios run.
- `anthropic`: `claude-opus-5` via the `anthropic` SDK, `messages.create` with `output_config={"format": {"type": "json_schema", "schema": ...}}`, system prompt says fenced content is data. Lazy import; a clear error if the SDK is missing.

Every external string goes inside `<<<EXTERNAL_CONTENT app= field= resource=>>> … <<<END_EXTERNAL_CONTENT>>>` with `<<<` inside the content broken up. Display names too.

Drafts of both files exist from earlier work; ask for them if useful.

### A3 `agent/policy.py`

Deterministic, overrides the model, logs every override as `finding override:<key>` with the class prevented.

- `signals(app, candidate, hr_record) -> set[str]` from `{"email","name","handle"}`. Accept with two or more. Drive: email counts as two (the email is the account). Slack without email: `needs_human` for the app (D7).
- `enforce(items, proposals) -> dict[key, Disposition]` applying R1–R8 from PLAN.md Appendix B. The rules never read `content`; `detect_injection(content)` only logs `finding injection:<app>:<resource>`.
- `enforce_order(actions, proposed) -> list[Action]` with the order in CONTRACT.md. Log `finding override:order` when the model's order was changed.
- `verify_summary(sentences, steps) -> (kept, dropped)`: `[sN]` present, N exists, completion verbs need a gate step with `result.status == "applied"`. Dropped sentences: `finding unsupported_claim:<n>`.

### A4 `agent/loop.py`

`RunConfig` and `run_offboarding(config, drivers, model, tracer, gate)` per CONTRACT.md. Six `phase` steps. Emit `identity`, `inventory`, `disposition`, `run_status`, `summary` events exactly as the contract table says. Wrap every model method call in a `model_call` step and copy `model.last_call` onto it.

Identity candidates: GitHub from `all_org_members()`, Slack from `all_users()`, Drive is the email. Inventory only for resolved apps. Partial failure per D3: first `failed_apply` on an irreversible action stops writes, emits `finding dirty_run` with all undo records of applied steps, `run_status dirty`, then still runs the report phase.

### A5 `agent/tools.py` and the report phase

`actions_for(item, disposition, drivers, config) -> list[Action + callables + undo]`, one branch per kind, table in PLAN.md Appendix C. Transfer of a Drive file leaves the old owner as writer; the follow-up revoke removes that permission by id found through `list_permissions` after the transfer.

Report: `log:evidence` appends one row per gate step so far to `config.evidence_sheet_id` through the gate (reversible, undo `delete_rows`). `notify:#it-offboarding` posts the verified summary through the gate (undo `delete_message` with the returned `ts`). Both are cut first if time runs out (D10).

### A6 Fix the two classes

Only after `baseline.json` is committed. Take the failing list from Track B, fix, do not touch scenarios (Track B owns them; if a scenario is wrong, write it in `REQUESTS.md`).

### A7 `cli.py`

`offboard run --user --mode twin|live [--dry-run] [--approve …] [--model …] [--trace] [--record|--replay]`, `offboard plan` (writes `plan.json`: every action, diff, risk, undo, hash), `offboard apply --plan plan.json` (gate approves only hashes present in the file), `offboard undo --trace file`. `.env` loaded by hand. The rendered trace tree is the only stdout.

### A8 `offboard undo`

Read a trace, take applied gate steps in reverse, build an `Action` from each undo record, execute through the gate. `supported: false` records are listed with their note and skipped.

### A9 Semantic cross-check (U7)

For irreversible ops, a second independent read where one exists; both must agree for the postcondition to pass. Needs new read ops in `RISK` and twin endpoints, which are frozen files: write the request in `REQUESTS.md` first and only build if Track B agrees quickly.

## Things not to do

Retry a failed destructive apply. Let the model see unfenced content. Skip the postcondition on reversible writes. Edit `adapters/` or `twins/` yourself. Fix anything before the baseline is committed.

### A10 Run Console (`report/console.py`), added 13 Sep

Static page from one trace: `python -m report.console --trace traces/demo.jsonl --out console.html`. Live: `--serve 8765` polls the JSONL. Sections and demo flow in PLAN.md addendum. Same visual tokens as the scorecard. Zero libraries. Build after A7/A8.
