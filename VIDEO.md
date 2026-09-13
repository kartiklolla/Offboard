# Two-minute demo: narration script

Video: `offboard-demo.mp4` — 1600×900, 103 seconds, silent. Read this over it.
Every frame is real captured output: no mockups, no re-typed terminals.

Target pace ~150 wpm. Total script ≈ 250 words, which leaves breathing room.

---

**0:00–0:04 · Title**

> Offboard revokes a departing employee's access across GitHub, Slack, Drive and Sheets — and proves it did so safely.

**0:04–0:11 · The problem**

> Offboarding fails silently. Every call returns two hundred. Revoke a shared folder and four colleagues lose it on Monday. Delete a deploy key and staging breaks at three a.m. A transcript is not evidence — so the eval harness is the product, and the agent is what it evaluates.

**0:11–0:20 · Four traps**

> Our fixture plants four traps a plausible agent fails: a shared folder that must be transferred before it is revoked, a deploy key that looks personal but runs the deploy job, two Slack handles one character apart, and three prompt injections telling the agent this account is exempt.

**0:20–0:28 · Architecture**

> The model never enumerates and never calls a destructive endpoint. It proposes; the policy layer decides. Every write goes through a five-stage gate ending in a postcondition read-back.

**0:28–0:35 · Evals**

> Twenty-nine seeded scenarios, one failure class each, scored from the trace file alone. Plus twenty-seven generated fault cells. No network, no keys, zero dependencies.

**0:35–0:44 · Mutants**

> A green board proves nothing, so we asked the other question: would the suite notice a defence going missing? We remove one at a time, at run time. Twelve removed, twelve caught — each by the class that claims to prove it.

**0:44–0:51 · The plan**

> Live now, against a real GitHub org. Nothing is applied without an approved plan. Delete a line and that write cannot happen.

**0:51–1:03 · The F5 catch** ← *the moment; slow down here*

> Watch this. GitHub returns two-oh-four — success. The read-back runs, retries, and still finds three collaborators. The gate calls it a failed postcondition, stops the run, and claims nothing. The leaver is an org member, so removing a collaborator is a no-op that reports success. We verified afterwards: access was genuinely unchanged. That is a silent failure caught live, on real GitHub.

**1:03–1:12 · The write that works**

> Removing org membership does work — and the read-back confirms it. The idle deploy key is deleted. The in-use one survives, escalated, with zero destructive calls against it.

**1:12–1:22 · Console**

> One run, read from the trace: dispositions with their rule, the injection logged, and each gate opened to its five stages.

**1:22–1:29 · Undo**

> Every irreversible action carries an undo record — including when the API cannot honour it. Here it refuses to pretend, and says why.

**1:29–1:38 · Scorecard**

> The scorecard reads only the trace. Pass rate per class, the fault matrix, and the mutant grid, where a red cell would be a defence we would not notice losing.

**1:38–1:43 · Close**

> One forty-six tests, twenty-nine scenarios, twelve mutants — and three models, including Claude Opus 5, producing identical dispositions. The policy layer decides, not the model. Drive and Sheets stayed on twins, and that is on the scorecard too.

---

## If you record your own voice

- The F5 slide at 0:51 is the one that wins the room. Pause a beat after "success."
- Say "two-oh-four", not "two hundred and four".
- The honest limitation at the end is a feature, not an apology. Say it flatly.
