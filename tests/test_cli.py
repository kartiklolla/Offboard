from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import cli
from core.trace import load_trace


def run_cli(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


class PlanApplyUndo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def path(self, name: str) -> str:
        return os.path.join(self.tmp, name)

    def test_dry_run_exit_zero_and_no_writes(self) -> None:
        code, out = run_cli("run", "--user", "dhruv@acme.dev", "--dry-run", "--trace", self.path("dry.jsonl"))
        self.assertEqual(code, 0)
        self.assertIn("dry_run", out)
        steps = load_trace(self.path("dry.jsonl"))
        self.assertEqual([s for s in steps if s["kind"] == "tool_call" and s["risk"] != "read"], [])

    def test_plan_edit_apply_honours_the_file(self) -> None:
        code, _ = run_cli("plan", "--user", "dhruv@acme.dev", "--trace", self.path("plan.jsonl"), "--out", self.path("plan.json"))
        self.assertEqual(code, 0)
        with open(self.path("plan.json")) as fh:
            plan = json.load(fh)
        self.assertEqual(len(plan["actions"]), 25)
        self.assertTrue(all(a["diff"] and a["hash"] for a in plan["actions"]))
        self.assertIn("github:deploy_key:dmehta-laptop", [e["key"] for e in plan["escalated"]])

        plan["actions"] = [a for a in plan["actions"] if a["name"] != "revoke:#deploys"]
        for a in plan["actions"]:
            if a["name"] == "revoke:acme":
                a["approved"] = False
        with open(self.path("plan.json"), "w") as fh:
            json.dump(plan, fh)

        code, out = run_cli("apply", "--plan", self.path("plan.json"), "--trace", self.path("apply.jsonl"), "--save-state", self.path("state.json"))
        self.assertEqual(code, 2)
        steps = load_trace(self.path("apply.jsonl"))
        status = {s["name"]: s["result"]["status"] for s in steps if s["kind"] == "gate"}
        self.assertEqual(status["revoke:#deploys"], "needs_approval")
        self.assertEqual(status["revoke:acme"], "needs_approval")
        self.assertEqual(status["revoke:acme/billing"], "applied")
        self.assertEqual(status["transfer:billing-runbooks"], "applied")
        with open(self.path("state.json")) as fh:
            state = json.load(fh)
        kicks = [s for s in steps if s["kind"] == "tool_call" and s["name"] == "kick_from_channel"]
        self.assertFalse(any(k["args"].get("channel") == "C_DEPLOYS" for k in kicks))
        self.assertEqual(len(kicks), 5)
        self.assertIn("dmehta", state["github"]["members_logins"])

    def test_dirty_run_then_undo_restores(self) -> None:
        code, _ = run_cli("run", "--user", "dhruv@acme.dev", "--approve", "all", "--trace", self.path("run.jsonl"),
                          "--save-state", self.path("state.json"), "--fault", "remove_permission:http_500:2")
        self.assertEqual(code, 1)
        code, out = run_cli("undo", "--trace", self.path("run.jsonl"), "--state", self.path("state.json"),
                            "--out-trace", self.path("undo.jsonl"), "--save-state", self.path("after.json"))
        self.assertEqual(code, 0)
        undo = load_trace(self.path("undo.jsonl"))
        final = undo[-1]["result"]
        self.assertEqual(final["failed"], 0)
        self.assertEqual(final["restored"], final["source_applied"])
        with open(self.path("after.json")) as fh:
            after = json.load(fh)
        runbooks = next(f for f in after["drive"]["files"] if f["name"] == "billing-runbooks")
        self.assertEqual(runbooks["owner"], "dhruv@acme.dev")
        self.assertTrue(all(s["kind"] != "tool_call" or s["risk"] == "read" or s.get("parent") for s in undo))

    def test_unsupported_undo_is_skipped_with_note(self) -> None:
        run_cli("run", "--user", "dhruv@acme.dev", "--approve", "all", "--trace", self.path("run.jsonl"), "--save-state", self.path("state.json"))
        code, _ = run_cli("undo", "--trace", self.path("run.jsonl"), "--state", self.path("state.json"), "--out-trace", self.path("undo.jsonl"))
        undo = load_trace(self.path("undo.jsonl"))
        skipped = {s["name"]: s["note"] for s in undo if s["kind"] == "skipped"}
        self.assertIn("undo:acme", skipped)
        self.assertIn("undo:dmehta-old-laptop", skipped)
        self.assertIn("invitation", skipped["undo:acme"])
        self.assertEqual(undo[-1]["result"]["skipped_unsupported"], 2)

    def test_fault_flag_parsing(self) -> None:
        plan = cli.parse_faults(["transfer_ownership:silent_noop:1:file=D_RUNBOOKS"])
        self.assertEqual(plan.faults[0].match, {"file": "D_RUNBOOKS"})
        self.assertEqual(plan.faults[0].on_call, 1)


if __name__ == "__main__":
    unittest.main()
