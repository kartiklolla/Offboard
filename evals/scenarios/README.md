# Scenario schema

One JSON file per scenario, validated by `evals/schema.py` (`load_all()` raises `ScenarioError` on the first bad file). Every scenario asserts against exactly one failure class.

## Top level

| Key | Type | Meaning |
|---|---|---|
| `id` | string | unique, also the trace file name |
| `description` | string | optional, one line |
| `seed` | string | fixture name under `twins/fixtures/` (`acme`) |
| `target` | email | the departing employee |
| `model` | `heuristic` \| `gullible` \| `anthropic` | `gullible` deliberately follows injections and guesses identities, to prove the policy layer overrides it |
| `faults` | list | `{"op", "mode", "on_call", "match"}`; `mode` is one of `http_500`, `rate_limit_429`, `silent_noop`, `stale_read`, `partial_page`; `on_call` is the 1-based attempt the fault fires on; `match` narrows by call args, e.g. `{"repo": "acme/billing"}` |
| `patch` | list | fixture edits applied before the run: `{"op": "set" \| "delete", "path": "slack/users/3/email", "value": ...}` |
| `dry_run` | bool | nothing applied, every diff still produced |
| `approvals` | list | approval tokens handed to the gate; `["*"]` approves all irreversible actions |

## `expect`

Every key is optional except `failure_class_if_violated`.

| Key | Type | Assertion |
|---|---|---|
| `failure_class_if_violated` | `F1`..`F8` or `H` | the class the scenario proves |
| `dispositions` | `{item_key: disposition}` | item keys are `app:kind:resource_name` (`AccessItem.key`), e.g. `github:deploy_key:dmehta-laptop` |
| `order_before` | `[[before, after]]` | gate step names, `verb:resource`, e.g. `transfer:billing-runbooks` |
| `postconditions` | `[{actor, resource, has_access}]` | checked against twin state after the run via `TwinState.has_access` |
| `forbidden_calls` | `["op:resource"]` | no `tool_call` trace step with that op touching that resource |
| `required_calls` | `["op:resource"]` | at least one such step exists |
| `identity` | `{app: principal_id \| "needs_human"}` | identity resolution outcome per app |
| `inventory_contains` | `[item_key]` | item reached the inventory (F6) |
| `findings_min` | `{class: n}` | at least n `finding` steps of that class (F7 uses 1 per payload) |
| `gate_status` | `{gate_step_name: status}` | e.g. `{"revoke:acme/billing": "failed_postcondition"}` (F5) |
| `run_status` | string | e.g. `dirty` after a mid-plan 500 (F4) |
| `undo_records_for_applied` | bool | every applied gate step carries an `undo` record |
| `no_writes_after_failure` | bool | no destructive `tool_call` after the first `failed_apply` |
| `report_cited` | bool | every sentence of the posted summary cites an existing step id (F8) |
| `evidence_rows_match_gate_steps` | bool | Sheets evidence log has one row per gate step |

## Naming conventions the runner depends on

- `tool_call` steps are named by operation (`remove_collaborator`) with `args` carrying `app` and the resource identifiers.
- `gate` steps are named `verb:resource` where verb is `transfer`, `revoke`, `log` or `notify`.
- `finding` steps carry `failure_class`.
