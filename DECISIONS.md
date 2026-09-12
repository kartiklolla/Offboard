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

