from __future__ import annotations

import os
import tempfile
import unittest

from adapters.base import RiskTier
from adapters.registry import build_drivers
from core import gate as G
from core.budget import Budget, BudgetExceeded
from core.trace import Tracer
from twins.faults import FaultPlan


class GateStatuses(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.tracer = Tracer(path=os.path.join(self.tmp, "t.jsonl"))

    def tearDown(self) -> None:
        self.tracer.close()

    def _drivers(self, faults: list[dict] | None = None):
        return build_drivers("twin", tracer=self.tracer, faults=FaultPlan.from_specs(faults or []))

    def _remove_collab(self, drivers, gate: G.Gate, repo: str = "acme/billing", login: str = "dmehta", **override) -> G.GateResult:
        gh = drivers.github
        self._last_gate = gate
        action = G.Action("github", "remove_collaborator", {"repo": repo, "login": login}, RiskTier.IRREVERSIBLE, repo, "revoke", f"github:repo_collaborator:{repo}")
        callables = dict(
            precondition=lambda: gh.has_access(login, repo),
            describe=lambda: f"-collaborator {login} (write) on {repo}",
            apply=lambda: gh.remove_collaborator(repo, login),
            postcondition=lambda: gh.has_access(login, repo) is False,
            undo={"op": "add_collaborator", "args": {"repo": repo, "login": login, "permission": "write"}},
        )
        callables.update(override)
        return gate.execute(action, **callables)

    def _gate_step(self):
        return [s for s in self.tracer.steps if s.kind == "gate"][-1]

    def test_applied(self) -> None:
        d = self._drivers()
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}))
        self.assertEqual(r.status, G.APPLIED)
        self.assertFalse(d.github.has_access("dmehta", "acme/billing"))
        step = self._gate_step()
        self.assertEqual(step.result, {"status": "applied"})
        self.assertTrue(step.precondition["ok"])
        self.assertEqual(step.dry_run, "-collaborator dmehta (write) on acme/billing")
        self.assertTrue(step.approval["granted"])
        self.assertTrue(step.postcondition["ok"])
        self.assertEqual(step.undo["op"], "add_collaborator")
        self.assertTrue(step.undo["supported"])
        children = [s for s in self.tracer.steps if s.parent == step.step and s.kind == "tool_call"]
        self.assertTrue(any(c.name == "remove_collaborator" for c in children))

    def test_skipped_dry_run(self) -> None:
        d = self._drivers()
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}, dry_run=True))
        self.assertEqual(r.status, G.SKIPPED_DRY_RUN)
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))
        self.assertEqual(self._gate_step().dry_run, "-collaborator dmehta (write) on acme/billing")
        self.assertFalse(any(s.kind == "tool_call" and s.risk != "read" for s in self.tracer.steps))

    def test_blocked_precondition(self) -> None:
        d = self._drivers()
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}), login="ksingh")
        self.assertEqual(r.status, G.BLOCKED_PRECONDITION)
        self.assertIsNone(self._gate_step().dry_run)

    def test_needs_approval(self) -> None:
        d = self._drivers()
        r = self._remove_collab(d, G.Gate(self.tracer, set()))
        self.assertEqual(r.status, G.NEEDS_APPROVAL)
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))
        self.assertFalse(self._gate_step().approval["granted"])

    def test_approval_tokens(self) -> None:
        d = self._drivers()
        action = G.Action("github", "remove_collaborator", {}, RiskTier.IRREVERSIBLE, "acme/billing", "revoke")
        for tokens in ({"*"}, {"github"}, {"revoke"}, {"github:remove_collaborator:acme/billing"}, {action.hash}):
            self.assertTrue(G.Gate(self.tracer, tokens).approved(action), tokens)
        self.assertFalse(G.Gate(self.tracer, {"slack"}).approved(action))
        reversible = G.Action("slack", "kick_from_channel", {}, RiskTier.REVERSIBLE, "#deploys", "revoke")
        self.assertTrue(G.Gate(self.tracer, set()).approved(reversible))

    def test_failed_apply_not_retried(self) -> None:
        d = self._drivers([{"op": "remove_collaborator", "mode": "http_500", "on_call": 1}])
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}))
        self.assertEqual(r.status, G.FAILED_APPLY)
        self.assertIn("500", r.error or "")
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))
        self.assertEqual(sum(1 for s in self.tracer.steps if s.name == "remove_collaborator"), 1)

    def test_failed_postcondition_is_f5(self) -> None:
        d = self._drivers([{"op": "remove_collaborator", "mode": "silent_noop", "on_call": 1}])
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}))
        self.assertEqual(r.status, G.FAILED_POSTCONDITION)
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))
        step = self._gate_step()
        self.assertEqual(step.failure_class, "F5")
        self.assertEqual(step.postcondition["attempts"], 2)

    def test_precondition_exception_blocks_without_applying(self) -> None:
        d = self._drivers()

        def boom() -> bool:
            raise KeyError("repo vanished")

        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}), precondition=boom)
        self.assertEqual(r.status, G.BLOCKED_PRECONDITION)
        self.assertIn("KeyError", r.error or "")
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))
        self.assertEqual(self._gate_step().result, {"status": "blocked_precondition"})

    def test_describe_exception_blocks_without_applying(self) -> None:
        d = self._drivers()
        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}), describe=lambda: 1 // 0)
        self.assertEqual(r.status, G.BLOCKED_PRECONDITION)
        self.assertTrue(d.github.has_access("dmehta", "acme/billing"))

    def test_postcondition_exception_is_unverified_f5(self) -> None:
        d = self._drivers()

        def boom() -> bool:
            raise RuntimeError("read-back endpoint gone")

        r = self._remove_collab(d, G.Gate(self.tracer, {"*"}), postcondition=boom)
        self.assertEqual(r.status, G.FAILED_POSTCONDITION)
        self.assertEqual(self._gate_step().failure_class, "F5")
        self.assertIn("read-back endpoint gone", r.error or "")
        self.assertIn(r, self.tracer_gate_results(d))

    def tracer_gate_results(self, d) -> list:
        return self._last_gate.results

    def test_write_budget_checked_before_apply(self) -> None:
        self.tracer.close()
        budget = Budget(max_writes=1)
        self.tracer = Tracer(path=os.path.join(self.tmp, "b.jsonl"), budget=budget)
        d = self._drivers()
        gate = G.Gate(self.tracer, {"*"})
        self.assertEqual(self._remove_collab(d, gate).status, G.APPLIED)
        with self.assertRaises(BudgetExceeded):
            self._remove_collab(d, gate, login="arjunrao")
        self.assertTrue(d.github.has_access("arjunrao", "acme/billing"))
        self.assertEqual(self._gate_step().result, {"status": "failed_apply"})
        self.assertEqual(len(gate.results), 2)

    def _remove_perm(self, drivers, gate: G.Gate, file_id: str = "D_ROADMAP", perm_id: str = "P_R1", email: str = "dhruv@acme.dev") -> G.GateResult:
        dr = drivers.drive
        has = lambda: any(p["email"] == email for p in dr.all_permissions(file_id))
        action = G.Action("drive", "remove_permission", {"file": file_id, "permission_id": perm_id}, RiskTier.IRREVERSIBLE, "eng-roadmap", "revoke", "drive:permission:eng-roadmap")
        return gate.execute(
            action,
            precondition=has,
            describe=lambda: f"-permission {email} (writer) on eng-roadmap",
            apply=lambda: dr.remove_permission(file_id, perm_id),
            postcondition=lambda: not has(),
            undo={"op": "add_permission", "args": {"file": file_id, "email": email, "role": "writer"}},
        )

    def test_stale_read_tolerated_by_retry(self) -> None:
        d = self._drivers([{"op": "list_permissions", "mode": "stale_read", "on_call": 2}])
        r = self._remove_perm(d, G.Gate(self.tracer, {"*"}))
        self.assertEqual(r.status, G.APPLIED)
        self.assertEqual(self._gate_step().postcondition["attempts"], 2)

    def test_stale_read_without_retry_would_false_alarm(self) -> None:
        d = self._drivers([{"op": "list_permissions", "mode": "stale_read", "on_call": 2}])
        r = self._remove_perm(d, G.Gate(self.tracer, {"*"}, postcondition_retries=0))
        self.assertEqual(r.status, G.FAILED_POSTCONDITION)


if __name__ == "__main__":
    unittest.main()
