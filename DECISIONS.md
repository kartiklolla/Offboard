# Decisions

One line per decision: the option chosen and one sentence why. Both Claude sessions read this before every chunk. Append, do not rewrite history; if a decision changes, add a new line with the date and time.

## Cross-track (agree at 09:30 PT)

| # | Decision | Chosen | Why | Who / when |
|---|---|---|---|---|
| D1 | Approval model | plan-then-apply (U1); tokens for the eval runner | built by A as `offboard plan` / `offboard apply`; the runner passes `["*"]` | default taken, B, 13 Sep 10:45 PT |
| D2 | Postcondition retry | 1, recorded on the step | in the gate as `postcondition.attempts` | default taken, B, 13 Sep 10:45 PT |
| D3 | Partial failure | stop, mark dirty, undo records, `offboard undo` | loop stops on the first failed apply or failed read-back; `offboard undo` exists | default taken, B, 13 Sep 10:45 PT |
| D4 | Runner reads | trace only | `score()` reads the JSONL and the twin end state, nothing from the agent | default taken, B, 13 Sep 10:45 PT |
| D5 | Model in evals | stubs for the suite, `claude-opus-5` for the demo | suite and mutants run on stubs; the third model column waits for `MODEL_API_KEY` | default taken, B, 13 Sep 10:45 PT |
| D6 | Authority | model proposes, policy overrides, every override traced | `finding override:<key>` when a class is prevented, `override` event otherwise | default taken, B, 13 Sep 10:45 PT |
| D7 | Slack without email | abstain for the app | `f1_missing_email_abstains` proves it; run ends `needs_human` | default taken, B, 13 Sep 10:45 PT |
| D8 | Scenario count | 28 hand-written + fault matrix | 28 + 27 generated, both green on the merged tree | default taken, B, 13 Sep 10:45 PT |
| D9 | Live scope | twins for everything until sandbox facts and `.env` exist; GitHub + Slack live if they arrive before 13:00 PT; Drive and Sheets stay twins | no accounts or tokens exist on either machine at 10:45 PT; a live dry run is a 30-minute job once they do | B, 13 Sep 10:45 PT |
| D10 | Report cut order | Sheets log, then summary, then live Drive, then report phase | nothing cut so far | default taken, B, 13 Sep 10:45 PT |
| D11 | Scorecard | static HTML with trace explorer | `report/scorecard.py`, plus A's `report/console.py` for the live view | default taken, B, 13 Sep 10:45 PT |
| D12 | Regression story | mutation testing instead of a red baseline: eleven defences removed one at a time, each caught by the class that claims to prove it | the baseline was 28/28 and 27/27; nothing failed, so there is no baseline-to-final delta to show, and manufacturing one would be dishonest (see B-h) | B, 13 Sep 10:45 PT |
| D13 | Upgrade set | U1 U2 U3 U5 U6 done; U8 done in the scorecard; U7 and U4 not started | U7 only if A has time before 14:00; U4 needs P3, which is not done | B, 13 Sep 10:45 PT |
| D14 | Track A / Track B | nobody named; both tracks take the plan's recommended answer and record it here | protocol rule 3: ten minutes without an answer means the recommendation is taken | B, 13 Sep 10:45 PT |
| D15 | Demo UI | static console page from the trace + optional stdlib poller; no framework, no write buttons | | Kartik, 13 Sep |

## Track A decisions

## Track B decisions

| # | Decision | Chosen | Why | When |
|---|---|---|---|---|
| B-a | Scoring input | trace steps plus the twin end state, nothing else | keeps `score()` pure and testable against a hand-written JSONL fixture before the loop exists | 12 Sep 23:40 |
| B-b | `forbidden_calls` / `required_calls` resolution | an alias map built from the fixture, so `delete_deploy_key:dmehta-laptop` matches the call that carries `key_id: 9003` | scenarios name resources the way a human does; ids live in the fixture | 12 Sep 23:40 |
| B-c | `undo_records_for_applied` scope | applied gate steps whose verb is `transfer` or `revoke` | Appendix C gives undo records for exactly those; `log` and `notify` are not access changes | 12 Sep 23:40 |
| B-d | Two automatic checks with no scenario key | in a `dry_run` scenario every gate must carry a diff and no destructive op may be called; in any scenario a declared fault must actually fire, and a 429 or 500 on a read must be followed by a successful retry | a scenario whose fault never fires is a silent pass, which is the failure mode TRACK_B warns about | 12 Sep 23:50 |
| B-e | `rate_limit_429` in the fault matrix | for write ops it asserts the F4 dirty-run contract, not a retry | the retry policy gives writes exactly one attempt, so a 429 on a write escalates; TRACK_B's "two attempts" only holds for reads, which `h6` covers | 12 Sep 00:05 |
| B-g | Limitation box | read verbatim from the `Limitation text for the scorecard box:` line in this file; if it is blank the scorecard says so in red | the one honest limitation is the Director's sentence to write, not the builder's to invent | 13 Sep 00:20 |
| B-h | Green baseline | keep it, and answer it with mutation testing: `evals/mutants.py` removes one defence at a time at run time (never editing Track A's files) and shows which scenarios go red | the first merged run was 28/28 and 27/27; the honest reply to "green from the first run reads as easy tests" is to prove the suite would catch each defence being lost, not to manufacture a red board | 13 Sep 10:05 PT |
| B-i | A 29th scenario after the baseline | `f1_two_qualifying_candidates`: a second Slack account with the target's name and email; both qualify, Slack must abstain | the mutation grid showed each identity rule caught by one scenario only; the baseline file keeps its 28 so the scorecard shows the addition rather than hiding it | 13 Sep 10:30 PT |
| B-f | Matrix scope | 9 write ops the twin run actually calls, times 3 modes, 27 generated; `--include-undo-ops` adds the 8 restore-only ops | ops the run never calls would fail on "the fault never fired" and say nothing about the agent | 12 Sep 00:05 |

## Sandbox facts (Track B fills in)

- GitHub org:
- Repos:
- Throwaway collaborator login:
- Deploy key title referenced from a workflow:
- Slack team id:
- Test user id and email:
- Channel ids:
- `#it-offboarding` channel id:
- Evidence sheet id:
- Prerequisites found by `tests/test_live.py` (B, 13 Sep 11:40 PT): the throwaway GitHub account's public profile **name** must equal the HR record name (`Dhruv Mehta`), because the org members endpoint carries no name or email and the driver now fetches each member's profile; without it GitHub has one signal and abstains. The Slack bot needs `channels:read` and `groups:read` on top of PLAN.md's list, or `conversations.list` and `conversations.members` fail with `missing_scope`. Set `SLACK_ENTERPRISE_GRID=1` only on a Grid workspace.

## Brief facts (Director fills in)

- Named user: Meera Shah, IT administrator at Acme (`meera@acme.dev` in the fixture, member of `#it-offboarding`), who today opens four admin consoles per leaver and keeps the evidence by hand. (B, default from PLAN.md, 13 Sep)
- Time-cost claim and its source: a manual offboarding across GitHub, Slack, Drive and an evidence spreadsheet takes an IT administrator one to two hours per leaver, and late or missing revocations are among the most common access-control exceptions in SOC 2 audits (Trust Services Criteria CC6.2 and CC6.3 require timely removal of access and evidence of it). Stated as a range and attributed to the criteria, not to a study we do not have. (B, default from PLAN.md, 13 Sep)
- Limitation text for the scorecard box: Slack deactivation through the API needs Enterprise Grid, so on a standard workspace the agent escalates it with an undo record that says the API cannot do it, and a human deactivates by hand. Every number on this page comes from runs against deterministic twins of the four apps; the live GitHub and Slack drivers exist but were not exercised against real sandboxes in this build. (B, 13 Sep)

## Parked (ideas that do not enter the build)

