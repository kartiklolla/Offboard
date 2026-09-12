# Decisions

One line per decision: the option chosen and one sentence why. Both Claude sessions read this before every chunk. Append, do not rewrite history; if a decision changes, add a new line with the date and time.

## Cross-track (agree at 09:30 PT)

| # | Decision | Chosen | Why | Who / when |
|---|---|---|---|---|
| D1 | Approval model | plan-then-apply (U1); tokens for the eval runner | | |
| D2 | Postcondition retry | 1, recorded on the step | | |
| D3 | Partial failure | stop, mark dirty, undo records, `offboard undo` | | |
| D4 | Runner reads | trace only | | |
| D5 | Model in evals | stubs for the suite, `claude-opus-5` for the demo | | |
| D6 | Authority | model proposes, policy overrides, every override traced | | |
| D7 | Slack without email | abstain for the app | | |
| D8 | Scenario count | 28 hand-written + fault matrix | | |
| D9 | Live scope | GitHub + Slack; Drive/Sheets only if P3 done | | |
| D10 | Report cut order | Sheets log, then summary, then live Drive, then report phase | | |
| D11 | Scorecard | static HTML with trace explorer | | |
| D12 | Regression story | whatever fails at baseline; commit before fixing | | |
| D13 | Upgrade set | U1 U2 U3 U5 U6, then U7 U8, U4 if P3 | | |
| D14 | Track A / Track B | | | |

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

## Brief facts (Director fills in)

- Named user:
- Time-cost claim and its source:
- Limitation text for the scorecard box:

## Parked (ideas that do not enter the build)

