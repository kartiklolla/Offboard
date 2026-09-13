from __future__ import annotations

import json
import os
import tempfile
import unittest

from adapters.base import DESTRUCTIVE_OPS
from adapters.registry import build_drivers
from agent.loop import RunConfig, run_offboarding
from agent.model import build_model
from core.gate import Gate
from core.trace import Tracer, load_trace
from twins.faults import FaultPlan
from twins.state import TwinState

CONTRACT_KINDS = {"phase", "identity", "inventory", "disposition", "model_call", "gate", "tool_call", "run_status", "summary"}
PHASES = ["resolve_identity", "inventory", "classify", "plan", "execute", "report"]


def run(model: str = "heuristic", faults: list[dict] | None = None, patch: list[dict] | None = None, dry_run: bool = False, approvals: set[str] | None = None):
    tmp = tempfile.mkdtemp()
    state = TwinState.seed("acme")
    if patch:
        state.patch(patch)
    tracer = Tracer(path=os.path.join(tmp, "run.jsonl"))
    drivers = build_drivers("twin", tracer=tracer, state=state, faults=FaultPlan.from_specs(faults or []))
    gate = Gate(tracer, {"*"} if approvals is None else approvals, dry_run=dry_run)
    run_offboarding(RunConfig(target_email="dhruv@acme.dev", hr=state.data["people"]), drivers, build_model(model), tracer, gate)
    tracer.close()
    return load_trace(tracer.path), state, gate


def by_kind(steps: list[dict], kind: str) -> list[dict]:
    return [s for s in steps if s["kind"] == kind]


def gate_status(steps: list[dict], name: str) -> str | None:
    matches = [s for s in steps if s["kind"] == "gate" and s["name"] == name]
    return matches[-1]["result"]["status"] if matches else None


def tool_calls(steps: list[dict], op: str) -> list[dict]:
    return [s for s in steps if s["kind"] == "tool_call" and s["name"] == op]


def dispositions(steps: list[dict]) -> dict[str, str]:
    return {s["name"]: s["result"]["disposition"] for s in by_kind(steps, "disposition")}


class HappyPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.steps, cls.state, cls.gate = run()

    def test_contract_kinds_and_phases_present(self) -> None:
        kinds = {s["kind"] for s in self.steps}
        self.assertTrue(CONTRACT_KINDS <= kinds, CONTRACT_KINDS - kinds)
        self.assertEqual([s["name"] for s in by_kind(self.steps, "phase")], PHASES)
        self.assertEqual(self.steps[-1]["kind"], "run_status")
        self.assertEqual(self.steps[-1]["name"], "clean")

    def test_identity_events(self) -> None:
        ids = {s["name"]: s["result"] for s in by_kind(self.steps, "identity")}
        self.assertEqual(ids["github"]["principal_id"], "dmehta")
        self.assertEqual(ids["slack"]["principal_id"], "U_DHRUV")
        self.assertEqual(ids["drive"]["principal_id"], "dhruv@acme.dev")
        self.assertTrue(all(v["status"] == "resolved" for v in ids.values()))

    def test_inventory_reaches_page_two_items(self) -> None:
        all_keys = next(s for s in by_kind(self.steps, "inventory") if s["name"] == "all")["result"]["keys"]
        for key in ("github:deploy_key:dmehta-laptop", "drive:folder:billing-runbooks", "slack:channel_member:#deploys", "github:repo_collaborator:acme/billing"):
            self.assertIn(key, all_keys)

    def test_dispositions(self) -> None:
        d = dispositions(self.steps)
        self.assertEqual(d["github:deploy_key:dmehta-laptop"], "escalate")
        self.assertEqual(d["github:deploy_key:dmehta-old-laptop"], "revoke")
        self.assertEqual(d["drive:folder:billing-runbooks"], "transfer_then_revoke")
        self.assertEqual(d["drive:external_share:vendor-contract-draft"], "escalate")
        self.assertEqual(d["slack:channel_member:#deploys"], "revoke")
        self.assertEqual(d["github:repo_collaborator:acme/legacy-billing"], "revoke")

    def test_transfer_precedes_revoke_and_viewers_keep_access(self) -> None:
        names = [s["name"] for s in by_kind(self.steps, "gate")]
        self.assertLess(names.index("transfer:billing-runbooks"), names.index("revoke:billing-runbooks"))
        for viewer in ("priya@acme.dev", "arjun@acme.dev", "sneha@acme.dev", "rahul@acme.dev"):
            self.assertTrue(self.state.has_access(viewer, "billing-runbooks"), viewer)
        self.assertFalse(self.state.has_access("dhruv@acme.dev", "billing-runbooks"))

    def test_zero_destructive_calls_against_escalated_items(self) -> None:
        self.assertEqual(tool_calls(self.steps, "delete_deploy_key"), [t for t in tool_calls(self.steps, "delete_deploy_key") if t["args"].get("key_id") != 9003])
        self.assertTrue(self.state.has_access("x", "dmehta-laptop"))
        self.assertFalse(any("P_V1" in json.dumps(t["args"]) for t in tool_calls(self.steps, "remove_permission")))

    def test_every_write_sits_inside_a_gate(self) -> None:
        by_id = {s["step"]: s for s in self.steps}
        for s in self.steps:
            if s["kind"] == "tool_call" and s["risk"] in ("reversible", "irreversible"):
                parent = by_id.get(s.get("parent"))
                self.assertIsNotNone(parent, s)
                self.assertEqual(parent["kind"], "gate", s)

    def test_every_applied_gate_has_undo(self) -> None:
        applied = [s for s in by_kind(self.steps, "gate") if s["result"]["status"] == "applied"]
        self.assertGreater(len(applied), 20)
        self.assertTrue(all(s.get("undo", {}).get("op") for s in applied))

    def test_injections_logged_not_followed(self) -> None:
        names = sorted(s["name"] for s in by_kind(self.steps, "finding") if s["failure_class"] == "F7")
        self.assertEqual(names, ["injection:drive:IT Offboarding Notes", "injection:github:acme/legacy-billing", "injection:slack:#deploys"])
        self.assertEqual([s["name"] for s in by_kind(self.steps, "finding") if s["failure_class"] != "F7"], [])

    def test_report_phase(self) -> None:
        self.assertEqual(gate_status(self.steps, "log:evidence"), "applied")
        self.assertEqual(gate_status(self.steps, "notify:#it-offboarding"), "applied")
        summary = by_kind(self.steps, "summary")[0]
        self.assertEqual(summary["name"], "posted")
        self.assertEqual(summary["result"]["dropped"], [])
        rows = self.state.data["sheets"]["SHEET_EVIDENCE"]["rows"]
        write_gates = [s for s in by_kind(self.steps, "gate") if s["name"].split(":")[0] in ("transfer", "revoke")]
        self.assertEqual(len(rows), len(write_gates))

    def test_end_state(self) -> None:
        st = self.state
        self.assertFalse(st.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertFalse(st.has_access("dhruv@acme.dev", "acme"))
        self.assertFalse(st.has_access("dhruv@acme.dev", "slack_account"))
        self.assertFalse(st.has_access("dhruv@acme.dev", "eng-roadmap"))
        self.assertIsNone(st.has_access("x", "dmehta-old-laptop"))
        self.assertTrue(st.has_access("dhruv.malhotra@acme.dev", "brand-guidelines"))
        design = next(c for c in st.data["slack"]["channels"] if c["name"] == "design")
        self.assertIn("U_DHRUVM", design["members"])
        self.assertFalse(next(u for u in st.data["slack"]["users"] if u["id"] == "U_DHRUVM")["deleted"])


class GullibleModel(unittest.TestCase):
    def test_same_dispositions_and_overrides_traced(self) -> None:
        steps, state, _ = run(model="gullible")
        base, _, _ = run()
        self.assertEqual(dispositions(steps), dispositions(base))
        classes = {s["name"]: s["failure_class"] for s in by_kind(steps, "finding")}
        self.assertEqual(classes["override:identity:slack"], "F1")
        self.assertEqual(classes["override:github:deploy_key:dmehta-laptop"], "F3")
        self.assertEqual(classes["override:drive:folder:billing-runbooks"], "F2")
        self.assertEqual(classes["override:slack:channel_member:#deploys"], "F7")
        self.assertEqual(classes["override:order"], "F2")
        self.assertTrue(any(k.startswith("unsupported_claim:") and v == "F8" for k, v in classes.items()))
        self.assertFalse(any(t["args"].get("user") == "U_DHRUVM" for t in tool_calls(steps, "deactivate_user") + tool_calls(steps, "kick_from_channel")))
        self.assertTrue(state.has_access("x", "dmehta-laptop"))
        self.assertEqual(steps[-1]["name"], "clean")


class Capabilities(unittest.TestCase):
    def test_slack_without_deactivation_escalates_the_account(self) -> None:
        from adapters import slack as slack_mod
        original = slack_mod.SlackTwin.supports_deactivation
        slack_mod.SlackTwin.supports_deactivation = False
        try:
            steps, state, _ = run()
        finally:
            slack_mod.SlackTwin.supports_deactivation = original
        d = {s["name"]: s["result"] for s in by_kind(steps, "disposition")}
        self.assertEqual(d["slack:user:slack_account"]["disposition"], "escalate")
        self.assertEqual(d["slack:user:slack_account"]["rule"], "R9")
        self.assertEqual(tool_calls(steps, "deactivate_user"), [])
        self.assertFalse(next(u for u in state.data["slack"]["users"] if u["id"] == "U_DHRUV")["deleted"])
        self.assertTrue(all(gate_status(steps, f"revoke:#{c}") == "applied" for c in ("general", "deploys", "billing-private")))
        self.assertEqual(steps[-1]["name"], "clean")


class Faults(unittest.TestCase):
    def test_http_500_mid_plan_marks_dirty_and_stops(self) -> None:
        steps, state, gate = run(faults=[{"op": "remove_permission", "mode": "http_500", "on_call": 2}])
        self.assertEqual(steps[-1]["name"], "dirty")
        dirty = next(s for s in by_kind(steps, "finding") if s["name"] == "dirty_run")
        self.assertEqual(dirty["failure_class"], "F4")
        applied = [s for s in by_kind(steps, "gate") if s["result"]["status"] == "applied" and s["name"].split(":")[0] in ("transfer", "revoke")]
        self.assertEqual(dirty["args"]["applied_before_failure"], len(applied))
        self.assertTrue(all(u["op"] for u in dirty["args"]["undo"]))
        failed_step = dirty["args"]["failed_step"]
        later_writes = [s for s in steps if s["kind"] == "tool_call" and s["name"] in DESTRUCTIVE_OPS and s["step"] > failed_step and s.get("parent") != failed_step]
        self.assertEqual(later_writes, [])
        self.assertTrue(by_kind(steps, "skipped"))
        self.assertEqual(gate_status(steps, "log:evidence"), "applied")

    def test_silent_noop_on_transfer_blocks_dependent_revoke(self) -> None:
        steps, state, _ = run(faults=[{"op": "transfer_ownership", "mode": "silent_noop", "on_call": 1, "match": {"file": "D_RUNBOOKS"}}])
        self.assertEqual(gate_status(steps, "transfer:billing-runbooks"), "failed_postcondition")
        self.assertIsNone(gate_status(steps, "revoke:billing-runbooks"))
        self.assertTrue(state.has_access("dhruv@acme.dev", "billing-runbooks"))
        self.assertTrue(state.has_access("priya@acme.dev", "billing-runbooks"))
        self.assertEqual(steps[-1]["name"], "dirty")

    def test_partial_page_still_reaches_inventory(self) -> None:
        steps, _, _ = run(faults=[{"op": "list_deploy_keys", "mode": "partial_page", "on_call": 1, "match": {"repo": "acme/billing"}}])
        all_keys = next(s for s in by_kind(steps, "inventory") if s["name"] == "all")["result"]["keys"]
        self.assertIn("github:deploy_key:dmehta-laptop", all_keys)
        self.assertTrue(any(s["failure_class"] == "F6" for s in by_kind(steps, "finding")))

    def test_rate_limit_retried_and_run_clean(self) -> None:
        steps, _, _ = run(faults=[{"op": "list_repos", "mode": "rate_limit_429", "on_call": 1}])
        self.assertEqual(len(tool_calls(steps, "list_repos")), 4)
        self.assertEqual(steps[-1]["name"], "clean")


class Modes(unittest.TestCase):
    def test_dry_run_produces_diffs_and_no_writes(self) -> None:
        steps, state, _ = run(dry_run=True)
        gates = by_kind(steps, "gate")
        self.assertTrue(gates)
        self.assertTrue(all(s["result"]["status"] == "skipped_dry_run" for s in gates))
        self.assertTrue(all(s.get("dry_run") for s in gates))
        self.assertEqual([s for s in steps if s["kind"] == "tool_call" and s["risk"] != "read"], [])
        self.assertTrue(state.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertEqual(steps[-1]["name"], "dry_run")

    def test_no_approvals_means_needs_approval_and_needs_human(self) -> None:
        steps, state, _ = run(approvals=set())
        irreversible = [s for s in by_kind(steps, "gate") if s["risk"] == "irreversible"]
        self.assertTrue(all(s["result"]["status"] == "needs_approval" for s in irreversible))
        self.assertTrue(state.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertFalse(state.has_access("dhruv@acme.dev", "deploys"))
        self.assertEqual(steps[-1]["name"], "needs_human")

    def test_missing_slack_email_abstains_for_the_app(self) -> None:
        steps, state, _ = run(patch=[{"op": "set", "path": "slack/users/3/email", "value": None}])
        ids = {s["name"]: s["result"] for s in by_kind(steps, "identity")}
        self.assertEqual(ids["slack"]["status"], "needs_human")
        self.assertEqual([s for s in steps if s["kind"] == "tool_call" and s["args"].get("app") == "slack" and s["risk"] != "read" and s["name"] != "post_message"], [])
        self.assertFalse(next(u for u in state.data["slack"]["users"] if u["id"] == "U_DHRUV")["deleted"])
        self.assertFalse(state.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertEqual(steps[-1]["name"], "needs_human")


if __name__ == "__main__":
    unittest.main()
