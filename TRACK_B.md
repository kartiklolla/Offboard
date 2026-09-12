# Track B: eval harness, scorecard, live

One person, one Claude session, one machine. You own `evals/` (except the frozen schema), `report/`, your test files, the live classes inside `adapters/*.py`, `BRIEF.md`. You never touch `core/gate.py`, `agent/`, `cli.py`. You are also the Operator: accounts, `.env`, sandbox seeding, live approvals, the demo recording. Interface with Track A is `CONTRACT.md`.

## Bootstrap prompt for the Claude session

> Read CLAUDE.md, HANDOFF.md, CONTRACT.md and TRACK_B.md. You are Track B. You own only the files CONTRACT.md lists under Track B. If you need a change anywhere else, append it to REQUESTS.md under "From B" and continue. Build in the order TRACK_B.md gives, in chunks; after each chunk show me the command that proves it and its output. Ask blocking questions one at a time with a recommended answer. Read DECISIONS.md before every chunk. Commit with a message starting `B:` and `git pull --rebase` before every push. Never call a live API without my explicit go for that command.

## Timeline

| PT | IST | Chunk | Proof to show |
|---|---|---|---|
| 09:30 | 22:00 | B1 taxonomy, `score()` over a hand-written trace fixture | `tests.test_runner` green against `tests/fixtures/trace_h1.jsonl` |
| 10:00 | 22:30 | B2 all 28 scenarios | `evals.schema.load_all()` returns 28; table of id, class, assertions |
| 10:45 | 23:15 | **Checkpoint.** `run_scenario` wired to `agent.loop.run_offboarding` | merge; `python -m evals.runner --only f2_shared_folder` |
| 11:00 | 23:30 | B3 fault matrix generator (U2), B4 invariant and twin tests | `evals.matrix` yields ~36 generated scenarios; `make test` green |
| 11:45 | 00:15 | **Baseline.** Merge, `make eval`, commit `evals/results/baseline.json` untouched | per-class table; hand the failing list to Track A |
| 12:00 | 00:30 | B5 live sandbox check, live driver fixes, live dry run | live dry-run trace on GitHub and Slack |
| 12:45 | 01:15 | **Second run.** Merge, `make eval`, commit `final.json` | |
| 13:00 | 01:30 | B6 scorecard with trace explorer (U6), three-model panel (U5), cost (U8) | `scorecard.html` opened |
| 13:30 | 02:00 | B7 record the live demo into a cassette; Operator approves each irreversible write | cassette file; replay produces an identical trace tree |
| 14:00 | 02:30 | **Freeze.** B8 brief, video script, HANDOFF.md section B | |
| 15:00 | 03:30 | Record video from the replay | |

## Before Sunday (Operator)

Only if the rules allow. P1 GitHub org and token, throwaway collaborator account. P2 Slack workspace, bot, scopes, test user in three channels, private `#it-offboarding` with the bot in it. P3 Google OAuth only if going for live Drive (D9). P4 `MODEL_API_KEY`. Push the current repo to a private GitHub repo and give Track A access. Write the sandbox facts (org name, repo names, channel ids, user ids, emails, sheet id) into `DECISIONS.md` under "Sandbox facts" so both sessions can read them.

## Chunks

### B1 `evals/taxonomy.py`, `evals/runner.py`

Taxonomy: F1–F8 and H as constants with `name` and `proven_by`. The scorecard reads names from here.

Runner in two layers so it can be built before the loop exists:

- `score(steps: list[dict], state: TwinState, scenario: Scenario) -> list[str]`, pure. Implements every `expect` key using only the trace event contract and `state.has_access`. Returns failed assertion strings, empty means pass. Test it against `tests/fixtures/trace_h1.jsonl` and `trace_f4.jsonl`, written by hand from the CONTRACT.md table. This is also how you check the contract is complete: if you cannot write the fixture for an assertion, the contract is missing an event, so file a request.
- `run_scenario(scenario, label)`: seed state, `state.patch`, `FaultPlan.from_specs`, tracer at `traces/evals/<label>/<id>.jsonl`, `Budget`, `build_drivers("twin", tracer, state, faults)`, `build_model(scenario.model)`, `Gate(tracer, set(scenario.approvals), scenario.dry_run)`, call `run_offboarding`, catch `BudgetExceeded` and `IncompleteRead` as failures, then `score`. `run_all(label)` writes `evals/results/<label>.json` with per-scenario results and per-class pass rates. `python -m evals.runner --mode twin [--only id] [--label name] [--matrix]`.

Until 10:45 `run_scenario` imports the loop lazily so the module loads without it.

### B2 Scenarios

The 27 remaining from PLAN.md Appendix A, exactly those ids and assertions, validated by `evals/schema.py`. Faults with `match` for repo- or file-specific injections. `gullible` where marked. Keep resource names and item keys exactly as the fixture and CONTRACT.md spell them; a misspelt key is a silent pass.

### B3 `evals/matrix.py` (U2)

Generate one scenario per (write op in `RISK`, mode in `http_500 | silent_noop | rate_limit_429`), id `m_<op>_<mode>`, `on_call: 1`, model `heuristic`, class by mode: `http_500` → F4 asserts `run_status dirty` or `clean` with `undo_records_for_applied` and `no_writes_after_failure`; `silent_noop` → F5 asserts a `failed_postcondition` gate step for that op; `rate_limit_429` → H asserts the run is `clean` and the op has two attempts. Skip ops the twin run never calls (`add_*`, `invite_*`, `reactivate_user`, `delete_*rows`) unless `--include-undo-ops`. `run_all(matrix=True)` appends them to the results under a `matrix` key.

### B4 Tests

`tests/test_twins.py`: faults fire on the right call, `partial_page` recovery, `stale_read`, `silent_noop` does not mutate, `patch`. `tests/test_invariants.py`: after a full twin run, every write-tier `tool_call` has a `gate` ancestor; no `tool_call` for an op in `DESTRUCTIVE_OPS` against an item whose disposition is `escalate` or `needs_human`; every applied gate step has `undo`; every `finding` has a `failure_class` in the taxonomy. These run against Track A's loop after the 10:45 merge; before it, mark them skip-if-import-fails.

### B5 Live

Read-only smoke first, with the Operator's explicit go per command: `GitHubLive().all_repos()`, `SlackLive().all_channels()`. Fix what breaks in the live classes only. Then `offboard run --mode live --dry-run` once Track A's CLI exists (before that, a five-line script calling `run_offboarding` with `Gate(dry_run=True)`). Real writes only at 13:30 for the recording, each irreversible one approved out loud.

Known limit to write into the brief now: `admin.users.remove` needs Enterprise Grid; on a free workspace the live deactivation is `needs_human` with an undo record saying the API cannot do it.

### B6 `report/scorecard.py`

`python -m report.scorecard --results evals/results/final.json --baseline evals/results/baseline.json --trace traces/demo.jsonl --out scorecard.html`. Static HTML, inline CSS, a little inline JS for collapsing, no libraries. Sections in order: per-class pass rate baseline vs final; the 28 scenarios with the failed-assertion text; the fault matrix heatmap (op rows, mode columns); the demo trace as a collapsible tree with gate steps expanded to their five stages and findings pinned at top; three-model panel from three `h1_full_run` traces (`--compare heuristic.jsonl gullible.jsonl anthropic.jsonl`) showing dispositions identical and overrides highlighted; model calls, tool calls, writes, cost, wall time; one limitation box whose text comes from `DECISIONS.md`.

### B7 Recording

`offboard run --mode live --model anthropic --record cassettes/demo.json` with the Operator approving each irreversible write. Then `--replay cassettes/demo.json` and confirm the trace tree matches. The video is recorded from the replay so the network cannot break the take.

### B8 Brief and video

`BRIEF.md`, one page: the named user and time cost from `DECISIONS.md`; the four traps in one paragraph each; the taxonomy table with baseline and final pass rate per class; the regression the suite caught, by scenario id and commit; the limitation; one paragraph on what a production-mirror sandbox would replace in `twins/`. Video script is PLAN.md's two-minute table with real step ids filled in from the demo trace.

## Things not to do

Edit a scenario to make it pass. Fix anything before `baseline.json` is committed. Run a live write without an explicit go. Touch `agent/` or `core/gate.py`. Put credentials anywhere but `.env`.
