from __future__ import annotations

import os
import unittest
from html.parser import HTMLParser

from core.trace import load_trace
from report.scorecard import Trace, limitation_text, render

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
VOID = {"meta", "br", "hr", "img", "input", "link", "source"}

RESULTS = {
    "label": "final", "mode": "twin", "generated_at": "2026-09-13T12:45:00Z",
    "totals": {"scenarios": 2, "passed": 1, "rate": 0.5},
    "by_class": {
        "H": {"name": "Happy path", "total": 1, "passed": 1, "rate": 1.0},
        "F2": {"name": "Orphaned shared resource", "total": 1, "passed": 0, "rate": 0.0},
    },
    "scenarios": [
        {"id": "h1_full_run", "class": "H", "passed": True, "failures": [], "error": None,
         "trace": "traces/evals/final/h1_full_run.jsonl", "run_id": "r_1", "steps": 210, "writes": 25,
         "cost_usd": 0.03, "duration_ms": 410, "description": "A clean offboarding."},
        {"id": "f2_shared_folder", "class": "F2", "passed": False,
         "failures": ["order_before: 'revoke:billing-runbooks' (s71) ran before 'transfer:billing-runbooks' (s84)"],
         "error": None, "trace": "traces/evals/final/f2_shared_folder.jsonl", "run_id": "r_2", "steps": 180,
         "writes": 20, "cost_usd": 0.02, "duration_ms": 380, "description": "Shared folder."},
    ],
    "matrix": [
        {"id": "m_remove_collaborator_http_500", "class": "F4", "passed": True, "failures": [], "error": None,
         "trace": "", "run_id": "r_3", "steps": 90, "writes": 4, "cost_usd": 0.0, "duration_ms": 70,
         "description": ""},
        {"id": "m_remove_collaborator_silent_noop", "class": "F5", "passed": False,
         "failures": ["findings_min: 0 F5 findings, expected at least 1"], "error": None, "trace": "",
         "run_id": "r_4", "steps": 95, "writes": 5, "cost_usd": 0.0, "duration_ms": 72, "description": ""},
    ],
    "matrix_by_class": {},
}

BASELINE = {
    "label": "baseline", "mode": "twin", "generated_at": "2026-09-13T11:45:00Z",
    "totals": {"scenarios": 2, "passed": 0, "rate": 0.0},
    "by_class": {
        "H": {"name": "Happy path", "total": 1, "passed": 0, "rate": 0.0},
        "F2": {"name": "Orphaned shared resource", "total": 1, "passed": 0, "rate": 0.0},
    },
    "scenarios": [dict(RESULTS["scenarios"][0], passed=False), dict(RESULTS["scenarios"][1], passed=False)],
    "matrix": [], "matrix_by_class": {},
}


class Balanced(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.bad: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.bad.append(tag)
        else:
            self.stack.pop()


def demo_trace() -> Trace:
    path = os.path.join(FIXTURES, "trace_h1.jsonl")
    return Trace("demo", path, load_trace(path))


class Scorecard(unittest.TestCase):
    def setUp(self) -> None:
        self.trace = demo_trace()
        self.html = render(RESULTS, BASELINE, self.trace, [self.trace, self.trace], "Slack deactivation needs Enterprise Grid.")

    def test_the_page_is_well_formed(self) -> None:
        parser = Balanced()
        parser.feed(self.html)
        self.assertEqual(parser.bad, [])
        self.assertEqual(parser.stack, [])

    def test_every_section_is_present(self) -> None:
        for title in ("Pass rate by failure class", "Every scenario, and what it asserted", "Fault matrix",
                      "step by step", "The same run under three models", "Cost and budget",
                      "What this does not do"):
            self.assertIn(title, self.html)

    def test_failed_assertions_are_printed_verbatim(self) -> None:
        self.assertIn("ran before", self.html)
        self.assertIn("findings_min: 0 F5 findings", self.html)

    def test_the_baseline_movement_is_named(self) -> None:
        self.assertIn(">fixed</span>", self.html)
        self.assertIn("h1_full_run", self.html)

    def test_gate_steps_show_all_five_stages(self) -> None:
        for stage in ("precondition", "diff", "approval", "read-back", "undo"):
            self.assertIn(f"<b>{stage}</b>", self.html)

    def test_findings_are_pinned_with_their_class(self) -> None:
        self.assertIn("injection:drive:IT Offboarding Notes", self.html)
        self.assertIn('href="#s13"', self.html)

    def test_no_external_resources(self) -> None:
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("<script src", self.html)

    def test_the_limitation_box_is_verbatim(self) -> None:
        self.assertIn("Slack deactivation needs Enterprise Grid.", self.html)

    def test_a_missing_limitation_says_so_instead_of_inventing_one(self) -> None:
        page = render(RESULTS, None, None, [], None)
        self.assertIn("Not written yet.", page)

    def test_limitation_is_read_from_the_decisions_file(self) -> None:
        import tempfile

        path = os.path.join(tempfile.mkdtemp(prefix="offboard-decisions-"), "DECISIONS.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("## Brief facts\n\n- Named user:\n- Limitation text for the scorecard box: Drive stays on the twin.\n")
        self.assertEqual(limitation_text(path), "Drive stays on the twin.")

    def test_an_empty_limitation_line_is_not_treated_as_text(self) -> None:
        import tempfile

        path = os.path.join(tempfile.mkdtemp(prefix="offboard-decisions-"), "DECISIONS.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("- Limitation text for the scorecard box:\n")
        self.assertIsNone(limitation_text(path))


if __name__ == "__main__":
    unittest.main()
