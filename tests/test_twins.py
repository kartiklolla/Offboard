from __future__ import annotations

import os
import tempfile
import unittest

from adapters.base import IncompleteRead, TransientError
from adapters.gdrive import DriveTwin
from adapters.github import GitHubTwin
from adapters.slack import SlackTwin
from core.trace import Tracer
from twins import faults as F
from twins.state import TwinState


def plan(*specs: dict) -> F.FaultPlan:
    return F.FaultPlan.from_specs(list(specs))


def tracer() -> Tracer:
    path = os.path.join(tempfile.mkdtemp(prefix="offboard-trace-"), "t.jsonl")
    return Tracer(path=path, mode="twin")


class FaultTiming(unittest.TestCase):
    def test_fault_fires_only_on_the_chosen_call(self) -> None:
        p = plan({"op": "list_repos", "mode": F.HTTP_500, "on_call": 2})
        self.assertIsNone(p.fire("list_repos", {"page": 1}))
        self.assertEqual(p.fire("list_repos", {"page": 2}), F.HTTP_500)
        self.assertIsNone(p.fire("list_repos", {"page": 3}))

    def test_match_narrows_by_args_and_counts_separately(self) -> None:
        p = plan({"op": "list_deploy_keys", "mode": F.PARTIAL_PAGE, "on_call": 1, "match": {"repo": "acme/billing"}})
        self.assertIsNone(p.fire("list_deploy_keys", {"repo": "acme/infra", "page": 1}))
        self.assertEqual(p.fire("list_deploy_keys", {"repo": "acme/billing", "page": 1}), F.PARTIAL_PAGE)
        self.assertIsNone(p.fire("list_deploy_keys", {"repo": "acme/billing", "page": 2}))

    def test_fired_faults_are_recorded(self) -> None:
        p = plan({"op": "deactivate_user", "mode": F.SILENT_NOOP, "on_call": 1})
        p.fire("deactivate_user", {"user": "U_DHRUV"})
        self.assertEqual(p.fired[0]["mode"], F.SILENT_NOOP)


class Pagination(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TwinState.seed("acme")

    def test_the_in_use_deploy_key_sits_on_page_two(self) -> None:
        github = GitHubTwin(self.state)
        page1 = github.list_deploy_keys("acme/billing", 1)
        page2 = github.list_deploy_keys("acme/billing", 2)
        self.assertNotIn("dmehta-laptop", [k["title"] for k in page1.items])
        self.assertIn("dmehta-laptop", [k["title"] for k in page2.items])
        self.assertEqual(page1.total, 3)

    def test_the_target_slack_user_sits_behind_the_decoy(self) -> None:
        slack = SlackTwin(self.state)
        page1 = slack.list_users(1)
        self.assertIn("U_DHRUVM", [u["id"] for u in page1.items])
        self.assertNotIn("U_DHRUV", [u["id"] for u in page1.items])

    def test_dropped_page_is_recovered_and_logged_as_f6(self) -> None:
        t = tracer()
        self.addCleanup(t.close)
        github = GitHubTwin(self.state, plan(
            {"op": "list_deploy_keys", "mode": F.PARTIAL_PAGE, "on_call": 1, "match": {"repo": "acme/billing"}}), tracer=t)
        keys = github.all_deploy_keys("acme/billing")
        self.assertEqual(len(keys), 3)
        self.assertIn("dmehta-laptop", [k["title"] for k in keys])
        findings = [s for s in t.steps if s.kind == "finding"]
        self.assertEqual([f.failure_class for f in findings], ["F6"])

    def test_a_page_that_never_comes_back_raises_incomplete_read(self) -> None:
        github = GitHubTwin(self.state, plan(
            {"op": "list_deploy_keys", "mode": F.PARTIAL_PAGE, "on_call": 1, "match": {"repo": "acme/billing"}},
            {"op": "list_deploy_keys", "mode": F.PARTIAL_PAGE, "on_call": 2, "match": {"repo": "acme/billing"}}))
        with self.assertRaises(IncompleteRead):
            github.all_deploy_keys("acme/billing")


class WriteFaults(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TwinState.seed("acme")

    def test_silent_noop_returns_200_and_changes_nothing(self) -> None:
        github = GitHubTwin(self.state, plan({"op": "remove_collaborator", "mode": F.SILENT_NOOP, "on_call": 1}))
        result = github.remove_collaborator("acme/billing", "dmehta")
        self.assertEqual(result["status"], 200)
        self.assertTrue(self.state.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertEqual(self.state.write_count, 0)

    def test_a_real_write_moves_the_state(self) -> None:
        github = GitHubTwin(self.state)
        github.remove_collaborator("acme/billing", "dmehta")
        self.assertFalse(self.state.has_access("dhruv@acme.dev", "acme/billing"))
        self.assertEqual(self.state.write_count, 1)

    def test_stale_read_shows_the_world_before_the_write(self) -> None:
        drive = DriveTwin(self.state, plan({"op": "list_permissions", "mode": F.STALE_READ, "on_call": 1}))
        drive.transfer_ownership("D_RUNBOOKS", "priya@acme.dev")
        stale = drive.list_permissions("D_RUNBOOKS", 1)
        fresh = drive.list_permissions("D_RUNBOOKS", 1)
        self.assertIn("priya@acme.dev", [p["email"] for p in stale.items])
        self.assertEqual(self.state.data["drive"]["files"][3]["owner"], "priya@acme.dev")
        self.assertNotEqual([p["id"] for p in stale.items], [p["id"] for p in fresh.items])

    def test_reads_retry_and_writes_do_not(self) -> None:
        t = tracer()
        self.addCleanup(t.close)
        github = GitHubTwin(self.state, plan({"op": "list_repos", "mode": F.RATE_LIMIT_429, "on_call": 1}), tracer=t)
        self.assertEqual(len(github.all_repos()), 5)
        attempts = [s for s in t.steps if s.kind == "tool_call" and s.name == "list_repos"]
        self.assertEqual(attempts[0].error, "HTTP 429 twin injected rate limit")
        self.assertIsNotNone(attempts[1].result)

        writer = GitHubTwin(self.state, plan({"op": "remove_collaborator", "mode": F.RATE_LIMIT_429, "on_call": 1}), tracer=t)
        with self.assertRaises(TransientError):
            writer.remove_collaborator("acme/billing", "dmehta")
        writes = [s for s in t.steps if s.kind == "tool_call" and s.name == "remove_collaborator"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(self.state.has_access("dhruv@acme.dev", "acme/billing"))


class StateEditing(unittest.TestCase):
    def test_patch_edits_the_fixture_before_the_run_and_survives_reset(self) -> None:
        state = TwinState.seed("acme")
        state.patch([{"op": "set", "path": "slack/users/3/email", "value": None}])
        slack = SlackTwin(state)
        self.assertEqual(slack.get_user("U_DHRUV")["real_name"], "Dhruv Mehta")
        self.assertIsNone(slack.get_user("U_DHRUV")["email"])
        state.reset()
        self.assertIsNone(slack.get_user("U_DHRUV")["email"])

    def test_snapshot_is_isolated_from_later_writes(self) -> None:
        state = TwinState.seed("acme")
        before = state.snapshot()
        SlackTwin(state).kick_from_channel("C_DEPLOYS", "U_DHRUV")
        self.assertIn("U_DHRUV", before["slack"]["channels"][4]["members"])
        self.assertNotIn("U_DHRUV", state.data["slack"]["channels"][4]["members"])

    def test_has_access_oracle_covers_all_three_apps(self) -> None:
        state = TwinState.seed("acme")
        self.assertTrue(state.has_access("dhruv@acme.dev", "acme"))
        self.assertTrue(state.has_access("dhruv@acme.dev", "#deploys"))
        self.assertTrue(state.has_access("rohan.contractor@gmail.com", "vendor-contract-draft"))
        self.assertFalse(state.has_access("neha@acme.dev", "billing-runbooks"))
        self.assertIsNone(state.has_access("dhruv@acme.dev", "no-such-resource"))


if __name__ == "__main__":
    unittest.main()
