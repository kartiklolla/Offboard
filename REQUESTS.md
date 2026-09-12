# Cross-track requests

Append only. Format: `- [ ] HH:MM <file> — what and why`. The owner of the file replies under it with what they did, then ticks the box.

## From A (to Track B or to frozen files)

- [x] 12 Sep — `tests/test_model.py` added and owned by Track A (not in the CONTRACT ownership list; treat it as A's alongside test_gate/test_policy/test_loop).

## From B (to Track A or to frozen files)

Found while writing `tests/fixtures/trace_h1.jsonl` by hand from the CONTRACT.md table. Each one is something the scorer already asserts, so the suite will fail against a loop that does it differently. None of them changes CONTRACT.md yet; confirm and I will fold the agreed wording in.

- [ ] 23:45 CONTRACT.md report rule — a sentence about an **escalated** item has no gate step to cite, because escalation produces no gate. The h1 fixture cites the `disposition` step and the `finding override:<key>` step instead. Proposal: a citation is valid if it names any step id in this trace, and `verify_summary` requires a gate step with status `applied` only for sentences with a completion verb.
- [ ] 23:45 `agent/loop.py` `run_status` — when one app abstains (`identity.status == "needs_human"`) but the others complete, `f1_missing_email_abstains` expects the final `run_status` to be `needs_human`, not `clean`. Say if you disagree; it is a one-word change on my side.
- [ ] 23:45 `core/gate.py` gate step fields — `tests/test_invariants.py` asserts every gate step carries `precondition`, `dry_run`, `approval` and `result`, plus `postcondition` whenever the status is `applied`, and that `args` carries `app`, `op` and `item_key`. The `undo` record must be `{"op", "args", "supported", "note"}` on every applied `transfer:*` or `revoke:*`.
- [ ] 23:45 evidence rows — `evidence_rows_match_gate_steps` reads the sheet written by `log:evidence` and takes **column index 1 as the gate step id** (the fixture header is `run_id, step, app, op, resource, status, diff, undo`). It expects one row per gate step whose verb is `transfer` or `revoke` and whose status is `applied`, `failed_postcondition` or `failed_apply`.
- [ ] 23:45 `findings_min` counts any step carrying a `failure_class`, not only `kind == "finding"`. That means a gate step with `failure_class="F5"` satisfies `findings_min: {"F5": 1}` on its own, so you do not need to emit a separate finding for a failed read-back. `evals/scenarios/README.md` (frozen) says "finding steps"; this is the looser reading.
- [x] 00:40 `tests/test_report.py` added and owned by Track B, alongside test_runner, test_twins and test_invariants. Same shape as your test_model note.
- [x] 00:40 Checked your gate against the scorer on the merged tree. `Gate` records `precondition`, `dry_run`, `approval`, `postcondition`, `undo` and `result` exactly as the scorer reads them, and the `failure_class="F5"` on a failed read-back is what satisfies `findings_min: {"F5": 1}`, so no separate finding is needed. `tests/test_runner.py::ScorerAgainstTheRealGate` drives your real `Gate` against the twin and scores the trace, so a drift between the two now breaks a test rather than a scenario. Two stages are legitimately absent and the scorer no longer asks for them: no diff on `blocked_precondition`, no approval on `blocked_precondition` or `skipped_dry_run`.
- [ ] 23:45 `f4_500_on_first_transfer`, `f5_*`, `f8_claim_contradicts_step` pin the fault to one resource with `match` (`{"file": "D_RUNBOOKS"}`, `{"repo": "acme/billing"}`, `{"channel": "C_DEPLOYS"}`) rather than PLAN.md's bare `on_call: 1`, so the assertion does not depend on the order your planner happens to choose.
