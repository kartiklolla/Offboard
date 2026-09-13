from __future__ import annotations

import unittest

from evals import schema
from evals.mutants import MUTANTS, by_id, run_mutant
from evals.runner import run_scenario

try:
    from evals.runner import _load_track_a

    _load_track_a()
    TRACK_A = True
    REASON = ""
except Exception as exc:  # noqa: BLE001
    TRACK_A = False
    REASON = f"the agent loop is not built yet: {exc}"


def scenarios_of(cls: str) -> list[schema.Scenario]:
    return [s for s in schema.load_all() if s.failure_class == cls]


@unittest.skipUnless(TRACK_A, REASON)
class MutantsAreCaught(unittest.TestCase):
    def test_every_mutant_names_a_class_the_taxonomy_knows(self) -> None:
        from evals.taxonomy import CLASSES

        for mutant in MUTANTS:
            for cls in mutant.expected_class.split():
                self.assertIn(cls, CLASSES)

    def test_removing_the_readback_is_caught_by_every_f5_scenario(self) -> None:
        row = run_mutant(by_id("a_200_is_the_truth"), scenarios_of("F5"), label="unit-mutants")
        self.assertEqual(row["survived"], [])
        self.assertEqual(row["killed_by_class"], {"F5": 3})

    def test_removing_the_two_signal_rule_is_caught_by_the_abstention_scenario(self) -> None:
        row = run_mutant(by_id("one_signal_is_enough"), scenarios_of("F1"), label="unit-mutants")
        self.assertIn("f1_missing_email_abstains", row["killed"])

    def test_the_patch_is_gone_after_the_mutant_exits(self) -> None:
        run_mutant(by_id("a_200_is_the_truth"), scenarios_of("F5")[:1], label="unit-mutants")
        clean = run_scenario(scenarios_of("F5")[0], label="unit-mutants/restored")
        self.assertTrue(clean.passed, clean.failures)

    def test_a_mutant_that_removes_nothing_survives(self) -> None:
        from contextlib import contextmanager

        from evals.mutants import Mutant

        @contextmanager
        def nothing():
            yield

        row = run_mutant(Mutant("noop", "nothing", "H", nothing), scenarios_of("F6"), label="unit-mutants")
        self.assertFalse(row["caught"])
        self.assertEqual(row["killed"], [])


if __name__ == "__main__":
    unittest.main()
