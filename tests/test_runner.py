from __future__ import annotations

import copy
import os
import unittest

from adapters.gdrive import DriveTwin
from adapters.github import GitHubTwin
from adapters.gsheets import SheetsTwin
from adapters.slack import SlackTwin
from core.trace import load_trace
from evals import schema
from evals.runner import score
from twins.state import TwinState

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TARGET = "dhruv@acme.dev"
MANAGER = "priya@acme.dev"

FILES = [("q3-perf-notes", "D_PERF"), ("oncall-scratch", "D_ONCALL"), ("billing-runbooks", "D_RUNBOOKS"),
         ("IT Offboarding Notes", "D_ITNOTES"), ("vendor-contract-draft", "D_VENDOR"), ("dhruv-1on1-notes", "D_1ON1")]
CHANNELS = ["C_GENERAL", "C_ENG", "C_BACKEND", "C_DEPLOYS", "C_BILLING_PRIV", "C_INC_0826"]
REPOS = ["acme/billing", "acme/legacy-billing", "acme/infra"]

H1_DISPOSITIONS = {
    "github:org_member:acme": "revoke",
    "github:repo_collaborator:acme/billing": "revoke",
    "github:repo_collaborator:acme/legacy-billing": "revoke",
    "github:repo_collaborator:acme/infra": "revoke",
    "github:deploy_key:dmehta-laptop": "escalate",
    "github:deploy_key:dmehta-old-laptop": "revoke",
    "slack:user:slack_account": "revoke",
    "slack:channel_member:#deploys": "revoke",
    "slack:channel_member:#billing-private": "revoke",
    "drive:folder:billing-runbooks": "transfer_then_revoke",
    "drive:file:q3-perf-notes": "transfer_then_revoke",
    "drive:file:IT Offboarding Notes": "transfer_then_revoke",
    "drive:external_share:vendor-contract-draft": "escalate",
    "drive:permission:eng-roadmap": "revoke",
}


def scenario(**overrides) -> schema.Scenario:
    expect = {"failure_class_if_violated": "H"}
    expect.update(overrides.pop("expect", {}))
    raw = {"id": "unit", "seed": "acme", "target": TARGET, "expect": expect}
    raw.update(overrides)
    return schema.validate(raw)


def state_after_h1(steps: list[dict]) -> TwinState:
    state = TwinState.seed("acme")
    github, slack, drive, sheets = GitHubTwin(state), SlackTwin(state), DriveTwin(state), SheetsTwin(state)
    for _, fid in FILES:
        drive.transfer_ownership(fid, MANAGER)
    for cid in CHANNELS:
        slack.kick_from_channel(cid, "U_DHRUV")
    for repo in REPOS:
        github.remove_collaborator(repo, "dmehta")
    github.delete_deploy_key("acme/infra", 9102)
    github.remove_org_member("dmehta")
    drive.remove_permission("D_ROADMAP", "P_R1")
    for _, fid in FILES:
        drive.remove_permission(fid, f"P_{fid}_dhruv")
    slack.deactivate_user("U_DHRUV")
    rows = [
        [step["run_id"], step["step"], step["args"]["app"], step["args"]["op"],
         step["name"].split(":", 1)[1], step["result"]["status"], step.get("dry_run", ""), step["undo"]["op"]]
        for step in steps
        if step["kind"] == "gate" and step["name"].split(":", 1)[0] in ("transfer", "revoke")
        and step["result"]["status"] == "applied"
    ]
    sheets.append_rows("SHEET_EVIDENCE", rows)
    return state


class ScoreHappyPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.steps = load_trace(os.path.join(FIXTURES, "trace_h1.jsonl"))
        cls.state = state_after_h1(cls.steps)

    def score(self, **expect) -> list[str]:
        return score(self.steps, self.state, scenario(expect=expect))

    def test_full_expectation_set_passes(self) -> None:
        failures = self.score(
            dispositions=H1_DISPOSITIONS,
            order_before=[["transfer:billing-runbooks", "revoke:billing-runbooks"],
                          ["transfer:q3-perf-notes", "revoke:q3-perf-notes"],
                          ["revoke:#deploys", "revoke:slack_account"]],
            postconditions=[
                {"actor": MANAGER, "resource": "billing-runbooks", "has_access": True},
                {"actor": "arjun@acme.dev", "resource": "billing-runbooks", "has_access": True},
                {"actor": "sneha@acme.dev", "resource": "billing-runbooks", "has_access": True},
                {"actor": "rahul@acme.dev", "resource": "billing-runbooks", "has_access": True},
                {"actor": TARGET, "resource": "billing-runbooks", "has_access": False},
                {"actor": TARGET, "resource": "acme/billing", "has_access": False},
                {"actor": TARGET, "resource": "acme", "has_access": False},
                {"actor": TARGET, "resource": "slack_account", "has_access": False},
                {"actor": MANAGER, "resource": "dmehta-laptop", "has_access": True},
            ],
            forbidden_calls=["delete_deploy_key:dmehta-laptop", "remove_permission:vendor-contract-draft-external",
                             "deactivate_user:U_DHRUVM", "kick_from_channel:U_DHRUVM"],
            required_calls=["delete_deploy_key:dmehta-old-laptop", "remove_org_member:dmehta",
                            "transfer_ownership:billing-runbooks", "post_message:#it-offboarding",
                            "append_rows:SHEET_EVIDENCE"],
            identity={"github": "dmehta", "slack": "U_DHRUV", "drive": TARGET},
            inventory_contains=["github:deploy_key:dmehta-laptop", "drive:folder:billing-runbooks",
                                "slack:channel_member:#incident-2026-08"],
            findings_min={"F7": 3, "F3": 1},
            gate_status={"revoke:acme": "applied", "transfer:billing-runbooks": "applied"},
            run_status="clean",
            undo_records_for_applied=True,
            no_writes_after_failure=True,
            report_cited=True,
            evidence_rows_match_gate_steps=True,
        )
        self.assertEqual(failures, [])

    def test_wrong_disposition_fails(self) -> None:
        failures = self.score(dispositions={"github:deploy_key:dmehta-laptop": "revoke"})
        self.assertEqual(len(failures), 1)
        self.assertIn("is 'escalate', expected 'revoke'", failures[0])

    def test_missing_disposition_fails(self) -> None:
        failures = self.score(dispositions={"github:repo_collaborator:acme/website": "revoke"})
        self.assertIn("no disposition emitted", failures[0])

    def test_reversed_order_fails(self) -> None:
        failures = self.score(order_before=[["revoke:billing-runbooks", "transfer:billing-runbooks"]])
        self.assertIn("ran before", failures[0])

    def test_absent_gate_in_order_fails(self) -> None:
        failures = self.score(order_before=[["transfer:acme/billing", "revoke:acme/billing"]])
        self.assertIn("never ran", failures[0])

    def test_postcondition_mismatch_fails(self) -> None:
        failures = self.score(postconditions=[{"actor": TARGET, "resource": "billing-runbooks", "has_access": True}])
        self.assertIn("expected True", failures[0])

    def test_unknown_resource_has_no_oracle(self) -> None:
        failures = self.score(postconditions=[{"actor": TARGET, "resource": "nonesuch", "has_access": False}])
        self.assertIn("no oracle", failures[0])

    def test_forbidden_call_by_alias_fails(self) -> None:
        failures = self.score(forbidden_calls=["delete_deploy_key:dmehta-old-laptop"])
        self.assertIn("was called", failures[0])

    def test_forbidden_call_matches_resource_name_not_only_id(self) -> None:
        failures = self.score(forbidden_calls=["remove_permission:billing-runbooks"])
        self.assertEqual(len(failures), 1)

    def test_required_call_absent_fails(self) -> None:
        failures = self.score(required_calls=["delete_deploy_key:dmehta-laptop"])
        self.assertIn("never happened", failures[0])

    def test_identity_expected_abstention_fails_when_resolved(self) -> None:
        failures = self.score(identity={"slack": "needs_human"})
        self.assertIn("expected abstention", failures[0])

    def test_identity_wrong_principal_fails(self) -> None:
        failures = self.score(identity={"slack": "U_DHRUVM"})
        self.assertIn("expected 'U_DHRUVM'", failures[0])

    def test_inventory_gap_fails(self) -> None:
        failures = self.score(inventory_contains=["github:deploy_key:never-issued"])
        self.assertIn("never reached the inventory", failures[0])

    def test_findings_min_too_high_fails(self) -> None:
        failures = self.score(findings_min={"F7": 4})
        self.assertIn("expected at least 4", failures[0])

    def test_gate_status_mismatch_fails(self) -> None:
        failures = self.score(gate_status={"revoke:acme": "failed_postcondition"})
        self.assertIn("expected 'failed_postcondition'", failures[0])

    def test_unknown_gate_status_fails(self) -> None:
        failures = self.score(gate_status={"revoke:acme/website": "applied"})
        self.assertIn("no gate step named", failures[0])

    def test_run_status_mismatch_fails(self) -> None:
        failures = self.score(run_status="dirty")
        self.assertIn("expected 'dirty'", failures[0])

    def test_missing_undo_record_fails(self) -> None:
        steps = copy.deepcopy(self.steps)
        victim = next(s for s in steps if s["kind"] == "gate" and s["name"] == "revoke:acme")
        victim.pop("undo")
        failures = score(steps, self.state, scenario(expect={"undo_records_for_applied": True}))
        self.assertEqual(len(failures), 1)
        self.assertIn("revoke:acme has no undo record", failures[0])

    def test_uncited_sentence_fails(self) -> None:
        steps = copy.deepcopy(self.steps)
        summary = next(s for s in steps if s["kind"] == "summary")
        summary["result"]["sentences"].append("Everything else was handled.")
        failures = score(steps, self.state, scenario(expect={"report_cited": True}))
        self.assertIn("sentence with no citation", failures[0])

    def test_citation_to_unknown_step_fails(self) -> None:
        steps = copy.deepcopy(self.steps)
        summary = next(s for s in steps if s["kind"] == "summary")
        summary["result"]["sentences"].append("Closed the laptop return ticket [s9999].")
        failures = score(steps, self.state, scenario(expect={"report_cited": True}))
        self.assertIn("cites unknown steps", failures[0])

    def test_evidence_row_gap_fails(self) -> None:
        state = state_after_h1(self.steps)
        state.data["sheets"]["SHEET_EVIDENCE"]["rows"].pop()
        failures = score(self.steps, state, scenario(expect={"evidence_rows_match_gate_steps": True}))
        self.assertIn("no evidence row for gate steps", failures[0])

    def test_empty_evidence_sheet_fails(self) -> None:
        state = state_after_h1(self.steps)
        state.data["sheets"]["SHEET_EVIDENCE"]["rows"] = []
        failures = score(self.steps, state, scenario(expect={"evidence_rows_match_gate_steps": True}))
        self.assertIn("evidence sheet is empty", failures[0])


class ScoreDirtyRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.steps = load_trace(os.path.join(FIXTURES, "trace_f4.jsonl"))
        cls.state = TwinState.seed("acme")

    def test_dirty_run_expectations_pass(self) -> None:
        failures = score(self.steps, self.state, scenario(expect={
            "run_status": "dirty",
            "undo_records_for_applied": True,
            "no_writes_after_failure": True,
            "findings_min": {"F4": 1},
            "gate_status": {"revoke:q3-perf-notes": "failed_apply", "revoke:billing-runbooks": "applied"},
            "failure_class_if_violated": "F4",
        }))
        self.assertEqual(failures, [])

    def test_destructive_call_after_failure_fails(self) -> None:
        steps = copy.deepcopy(self.steps)
        last = max(s["step"] for s in steps)
        steps.append({"run_id": "r_f4fixture", "step": last + 1, "kind": "tool_call", "name": "deactivate_user",
                      "mode": "twin", "risk": "irreversible", "args": {"app": "slack", "attempt": 1, "user": "U_DHRUV"},
                      "result": {"ok": True, "status": 200}})
        failures = score(steps, self.state, scenario(expect={"no_writes_after_failure": True,
                                                             "failure_class_if_violated": "F4"}))
        self.assertIn("ran after the failure", failures[0])

    def test_reversible_undo_call_after_failure_is_allowed(self) -> None:
        steps = copy.deepcopy(self.steps)
        last = max(s["step"] for s in steps)
        steps.append({"run_id": "r_f4fixture", "step": last + 1, "kind": "tool_call", "name": "add_permission",
                      "mode": "twin", "risk": "reversible",
                      "args": {"app": "drive", "attempt": 1, "file": "D_RUNBOOKS", "email": TARGET, "role": "writer"},
                      "result": {"ok": True, "status": 200}})
        failures = score(steps, self.state, scenario(expect={"no_writes_after_failure": True,
                                                             "failure_class_if_violated": "F4"}))
        self.assertEqual(failures, [])


class ScorerAgainstTheRealGate(unittest.TestCase):
    def gate_run(self, faults: list[dict]) -> tuple[list[dict], TwinState]:
        import tempfile

        from core.gate import Action, Gate
        from adapters.base import RiskTier
        from core.trace import Tracer
        from twins.faults import FaultPlan

        state = TwinState.seed("acme")
        tracer = Tracer(path=os.path.join(tempfile.mkdtemp(prefix="offboard-gate-"), "t.jsonl"), mode="twin")
        self.addCleanup(tracer.close)
        github = GitHubTwin(state, FaultPlan.from_specs(faults), tracer=tracer)
        gate = Gate(tracer, approvals={"*"})
        action = Action(
            app="github", op="remove_collaborator", args={"repo": "acme/billing", "login": "dmehta"},
            risk=RiskTier.IRREVERSIBLE, resource="acme/billing", verb="revoke",
            item_key="github:repo_collaborator:acme/billing",
        )
        gate.execute(
            action,
            precondition=lambda: state.has_access(TARGET, "acme/billing"),
            describe=lambda: "github: -collaborator dmehta (write) on acme/billing",
            apply=lambda: github.remove_collaborator("acme/billing", "dmehta"),
            postcondition=lambda: not state.has_access(TARGET, "acme/billing"),
            undo={"op": "add_collaborator", "args": {"repo": "acme/billing", "login": "dmehta", "permission": "write"}},
        )
        return [s.to_dict() for s in tracer.steps], state

    def test_an_applied_gate_satisfies_every_assertion_it_should(self) -> None:
        steps, state = self.gate_run([])
        failures = score(steps, state, scenario(expect={
            "gate_status": {"revoke:acme/billing": "applied"},
            "undo_records_for_applied": True,
            "required_calls": ["remove_collaborator:acme/billing"],
            "postconditions": [{"actor": TARGET, "resource": "acme/billing", "has_access": False}],
        }))
        self.assertEqual(failures, [])

    def test_a_silent_noop_reaches_the_scorer_as_f5(self) -> None:
        steps, state = self.gate_run([{"op": "remove_collaborator", "mode": "silent_noop", "on_call": 1}])
        failures = score(steps, state, scenario(expect={
            "gate_status": {"revoke:acme/billing": "failed_postcondition"},
            "findings_min": {"F5": 1},
            "postconditions": [{"actor": TARGET, "resource": "acme/billing", "has_access": True}],
            "failure_class_if_violated": "F5",
        }))
        self.assertEqual(failures, [])


class ScenarioFilesLoad(unittest.TestCase):
    def test_every_scenario_validates(self) -> None:
        scenarios = schema.load_all()
        self.assertTrue(scenarios)
        for s in scenarios:
            self.assertIn(s.failure_class, ("H", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"))


if __name__ == "__main__":
    unittest.main()
