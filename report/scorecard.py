from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from core.trace import load_trace, tree
from evals.matrix import MODES as FAULT_MODES
from evals.matrix import cells
from evals.taxonomy import CLASSES, ORDER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMITATION_KEY = "Limitation text for the scorecard box:"
STAGES = (("precondition", "precondition"), ("dry_run", "diff"), ("approval", "approval"),
          ("postcondition", "read-back"), ("undo", "undo"))

CSS = """
:root {
  --ink: #14161a; --muted: #5b6472; --line: #e2e5ea; --bg: #ffffff; --panel: #f7f8fa;
  --pass: #1a7f4b; --pass-bg: #e7f4ec; --fail: #b3261e; --fail-bg: #fdeceb;
  --warn: #8a6100; --warn-bg: #fdf3df; --accent: #2f4fd8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #e8eaee; --muted: #98a2b3; --line: #2b3038; --bg: #14161a; --panel: #1b1e24;
    --pass: #4ac286; --pass-bg: #14301f; --fail: #f2867d; --fail-bg: #331816;
    --warn: #e0b25c; --warn-bg: #2e2512; --accent: #8aa0ff;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 40px 24px 96px; }
h1 { font-size: 30px; letter-spacing: -0.02em; margin: 0 0 4px; }
h2 { font-size: 19px; letter-spacing: -0.01em; margin: 0 0 14px; }
h3 { font-size: 15px; margin: 22px 0 8px; }
.sub { color: var(--muted); margin: 0 0 28px; }
section { border-top: 1px solid var(--line); padding: 28px 0 8px; }
.headline { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 28px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 16px; min-width: 132px; flex: 1 1 132px; }
.stat .n { font-size: 26px; font-weight: 650; letter-spacing: -0.02em; display: block; }
.stat .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar { height: 7px; border-radius: 4px; background: var(--line); position: relative; min-width: 110px; }
.bar span { position: absolute; inset: 0 auto 0 0; border-radius: 4px; background: var(--pass); }
.bar.low span { background: var(--fail); }
.bar.mid span { background: var(--warn); }
.tag { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.tag.pass { color: var(--pass); background: var(--pass-bg); }
.tag.fail { color: var(--fail); background: var(--fail-bg); }
.tag.warn { color: var(--warn); background: var(--warn-bg); }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.fail-list { margin: 6px 0 0; padding-left: 18px; color: var(--fail); }
.fail-list li { margin: 2px 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
details { border-bottom: 1px solid var(--line); }
details > summary { cursor: pointer; padding: 7px 4px; list-style: none; display: flex; gap: 10px; align-items: baseline; }
details > summary::-webkit-details-marker { display: none; }
details > summary::before { content: "▸"; color: var(--muted); font-size: 11px; }
details[open] > summary::before { content: "▾"; }
.tree details { border: 0; }
.tree .leaf { padding: 3px 4px 3px 21px; display: flex; gap: 10px; align-items: baseline; }
.tree .kind { color: var(--muted); font-size: 12px; min-width: 88px; }
.tree .sid { color: var(--muted); font-size: 12px; min-width: 34px; text-align: right; }
.tree .gate { color: var(--accent); font-weight: 600; }
.tree .bad { color: var(--fail); }
.stages { margin: 2px 0 8px 55px; border-left: 2px solid var(--line); padding: 2px 0 2px 12px; }
.stages div { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; color: var(--muted); }
.stages b { color: var(--ink); font-weight: 600; }
.grid { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.cell { text-align: center; font-size: 12px; font-weight: 600; }
.cell.ok { color: var(--pass); background: var(--pass-bg); }
.cell.no { color: var(--fail); background: var(--fail-bg); }
.cell.na { color: var(--muted); }
.box { background: var(--panel); border: 1px solid var(--line); border-left: 3px solid var(--warn);
  border-radius: 8px; padding: 14px 18px; }
.box.todo { border-left-color: var(--fail); }
.pin { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; margin: 0 0 14px; }
.pin li { font-size: 13px; }
.controls { display: flex; gap: 8px; margin: 0 0 10px; }
button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 7px; cursor: pointer;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink); }
.muted { color: var(--muted); }
.same { color: var(--pass); font-weight: 600; }
.diff { color: var(--fail); font-weight: 600; }
"""

JS = """
function toggleAll(root, open) {
  document.querySelectorAll(root + ' details').forEach(function (d) { d.open = open; });
}
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _rate_class(rate: float) -> str:
    return "" if rate >= 0.9 else ("mid" if rate >= 0.6 else "low")


def _bar(rate: float) -> str:
    return f'<div class="bar {_rate_class(rate)}"><span style="width:{rate * 100:.0f}%"></span></div>'


def _pct(rate: float) -> str:
    return f"{rate * 100:.0f}%"


@dataclass
class Trace:
    label: str
    path: str
    steps: list[dict] = field(default_factory=list)

    @property
    def dispositions(self) -> dict[str, dict]:
        return {s["name"]: s.get("result") or {} for s in self.steps if s["kind"] == "disposition"}

    @property
    def findings(self) -> list[dict]:
        return [s for s in self.steps if s.get("failure_class")]


def load_results(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def limitation_text(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.lstrip().startswith("- " + LIMITATION_KEY):
                text = line.split(LIMITATION_KEY, 1)[1].strip(" -\t\n")
                return text or None
    return None


def header(results: dict, baseline: Optional[dict], demo: Optional[Trace], mutants: Optional[dict] = None) -> str:
    totals = results["totals"]
    stats = [("scenarios", totals["scenarios"]), ("passing", f"{totals['passed']}/{totals['scenarios']}"),
             ("pass rate", _pct(totals["rate"]))]
    if baseline:
        stats.insert(2, ("baseline rate", _pct(baseline["totals"]["rate"])))
    if results.get("matrix"):
        passed = sum(1 for r in results["matrix"] if r["passed"])
        stats.append(("fault matrix", f"{passed}/{len(results['matrix'])}"))
    if mutants:
        stats.append(("mutants caught", f"{mutants['totals']['caught']}/{mutants['totals']['mutants']}"))
    if demo:
        writes = sum(1 for s in demo.steps if s["kind"] == "tool_call" and s.get("risk") != "read")
        stats.append(("writes in the demo", writes))
    cards = "".join(f'<div class="stat"><span class="n">{esc(v)}</span><span class="k">{esc(k)}</span></div>'
                    for k, v in stats)
    return f'<div class="headline">{cards}</div>'


def per_class(results: dict, baseline: Optional[dict]) -> str:
    rows = []
    for cls in ORDER:
        final = results["by_class"].get(cls)
        if not final:
            continue
        base = (baseline or {}).get("by_class", {}).get(cls)
        delta = ""
        if base:
            change = final["rate"] - base["rate"]
            if abs(change) > 0.001:
                sign = "+" if change > 0 else "−"
                tag = "pass" if change > 0 else "fail"
                delta = f'<span class="tag {tag}">{sign}{abs(change) * 100:.0f}</span>'
        base_cell = "{}/{}".format(base["passed"], base["total"]) if base else "—"
        rows.append(
            f"<tr><td><code>{cls}</code></td><td>{esc(CLASSES[cls].name)}</td>"
            f'<td class="num muted">{esc(base_cell)}</td>'
            f'<td class="num">{final["passed"]}/{final["total"]}</td>'
            f'<td style="width:180px">{_bar(final["rate"])}</td>'
            f'<td class="num">{_pct(final["rate"])} {delta}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Class</th><th>Failure</th><th class='num'>Baseline</th>"
        "<th class='num'>Final</th><th>Rate</th><th class='num'>&nbsp;</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def movement(results: dict, baseline: Optional[dict]) -> str:
    if not baseline:
        return ""
    before = {r["id"]: r["passed"] for r in baseline["scenarios"] + baseline.get("matrix", [])}
    after = {r["id"]: r["passed"] for r in results["scenarios"] + results.get("matrix", [])}
    fixed = sorted(i for i, ok in after.items() if ok and before.get(i) is False)
    broken = sorted(i for i, ok in after.items() if not ok and before.get(i) is True)
    if not fixed and not broken:
        return '<p class="muted">Nothing moved between the two runs.</p>'
    parts = []
    if fixed:
        parts.append('<p><span class="tag pass">fixed</span> ' +
                     " ".join(f"<code>{esc(i)}</code>" for i in fixed) + "</p>")
    if broken:
        parts.append('<p><span class="tag fail">regressed</span> ' +
                     " ".join(f"<code>{esc(i)}</code>" for i in broken) + "</p>")
    return "".join(parts)


def scenario_rows(results: dict, baseline: Optional[dict]) -> str:
    before = {r["id"]: r["passed"] for r in (baseline or {}).get("scenarios", [])}
    blocks = []
    for cls in ORDER:
        rows = [r for r in results["scenarios"] if r["class"] == cls]
        if not rows:
            continue
        passed = sum(1 for r in rows if r["passed"])
        items = []
        for row in rows:
            tag = '<span class="tag pass">pass</span>' if row["passed"] else '<span class="tag fail">fail</span>'
            was = ""
            if row["id"] in before and before[row["id"]] != row["passed"]:
                was = '<span class="tag warn">changed</span>'
            failures = "<p class='muted'>Every assertion held.</p>"
            if row["failures"]:
                failures = '<ul class="fail-list">' + "".join(
                    f"<li>{esc(f)}</li>" for f in row["failures"]) + "</ul>"
            items.append(
                f'<details><summary>{tag} {was} <code>{esc(row["id"])}</code> '
                f'<span class="muted">{esc(row["description"])}</span></summary>'
                f'<div style="padding:4px 4px 12px 21px">{failures}'
                f'<p class="muted mono">{row["steps"]} steps · {row["writes"]} writes · '
                f'{row["duration_ms"]} ms · <a href="{esc(row["trace"])}">{esc(row["trace"])}</a></p></div></details>'
            )
        blocks.append(
            f'<h3><code>{cls}</code> {esc(CLASSES[cls].name)} '
            f'<span class="muted">{passed}/{len(rows)}</span></h3>' + "".join(items))
    return "".join(blocks)


def matrix_grid(results: dict) -> str:
    rows = results.get("matrix") or []
    if not rows:
        return '<p class="muted">This run did not include the generated fault matrix. Add <code>--matrix</code>.</p>'
    grid = cells(rows)
    head = "".join(f"<th class='num'>{esc(m)}</th>" for m in FAULT_MODES)
    body = []
    for op in sorted(grid):
        tds = []
        for mode in FAULT_MODES:
            cell = grid[op].get(mode)
            if cell is None:
                tds.append('<td class="cell na">—</td>')
            elif cell["passed"]:
                tds.append('<td class="cell ok" title="every invariant held">pass</td>')
            else:
                tds.append(f'<td class="cell no" title="{esc(" / ".join(cell["failures"])[:400])}">fail</td>')
        body.append(f"<tr><td><code>{esc(op)}</code></td>{''.join(tds)}</tr>")
    passed = sum(1 for r in rows if r["passed"])
    return (
        f'<p class="muted">{passed} of {len(rows)} generated scenarios hold. Every write operation in the risk map '
        f"crossed with every fault mode, asserting only the invariants. Hover a red cell for the assertion it broke.</p>"
        "<div class='grid'><table><thead><tr><th>write op</th>" + head + "</tr></thead><tbody>"
        + "".join(body) + "</tbody></table></div>"
    )


def mutation_grid(mutants: Optional[dict]) -> str:
    if not mutants:
        return ('<p class="muted">No mutation results were supplied. Run <code>python -m evals.mutants</code> and pass '
                "<code>--mutants evals/results/mutants.json</code>.</p>")
    rows = mutants["mutants"]
    classes = [c for c in ORDER if any(c in r["killed_by_class"] for r in rows)]
    head = "".join(f"<th class='num'>{esc(c)}</th>" for c in classes)
    body = []
    for row in rows:
        expected = set(row["expected_class"].split())
        tds = []
        for cls in classes:
            n = row["killed_by_class"].get(cls, 0)
            total = row["by_class"].get(cls, {}).get("total", 0)
            if not total:
                tds.append('<td class="cell na">—</td>')
            elif n and cls in expected:
                tds.append(f'<td class="cell ok" title="{n} of {total} {cls} scenarios went red">{n}/{total}</td>')
            elif n:
                tds.append(f'<td class="cell" title="{n} of {total} {cls} scenarios went red">{n}/{total}</td>')
            elif cls in expected:
                tds.append(f'<td class="cell no" title="the class that claims to prove this saw nothing">0/{total}</td>')
            else:
                tds.append(f'<td class="cell na">0/{total}</td>')
        verdict = ('<span class="tag pass">caught</span>' if row["caught_by_expected_class"]
                   else '<span class="tag warn">caught elsewhere</span>' if row["caught"]
                   else '<span class="tag fail">survived</span>')
        body.append(f"<tr><td>{verdict} <code>{esc(row['id'])}</code><br>"
                    f"<span class='muted'>removes {esc(row['removes'])}</span></td>{''.join(tds)}</tr>")
    totals = mutants["totals"]
    intro = (f"<p class='muted'>Each row removes one defence from the agent at run time, then runs all "
             f"{mutants['scenarios']} scenarios. A cell is how many scenarios of that class went red. "
             f"{totals['caught']} of {totals['mutants']} mutants were caught, {totals['caught_by_expected_class']} "
             f"by the class that claims to prove it. A red cell is a defence the suite would not notice losing.</p>")
    return intro + ("<div class='grid'><table><thead><tr><th>mutant</th>" + head + "</tr></thead><tbody>"
                    + "".join(body) + "</tbody></table></div>")


def cost_panel(demo: Optional[Trace], results: dict) -> str:
    if not demo or not demo.steps:
        total_cost = sum(r["cost_usd"] for r in results["scenarios"])
        return (f'<p class="muted">No demo trace was supplied. The suite itself spent '
                f"${total_cost:.4f} over {len(results['scenarios'])} runs.</p>")
    phases = [s for s in demo.steps if s["kind"] == "phase"]
    by_id = {s["step"]: s for s in demo.steps}

    def phase_of(step: dict) -> Optional[str]:
        node: Optional[dict] = step
        while node is not None:
            if node["kind"] == "phase":
                return node["name"]
            node = by_id.get(node.get("parent"))
        return None

    rows = []
    for phase in phases:
        owned = [s for s in demo.steps if phase_of(s) == phase["name"] and s["step"] != phase["step"]]
        model_calls = [s for s in owned if s["kind"] == "model_call"]
        tool_calls = [s for s in owned if s["kind"] == "tool_call"]
        writes = [s for s in tool_calls if s.get("risk") != "read"]
        cost = sum(s.get("cost_usd", 0.0) for s in owned)
        tokens = sum((s.get("tokens") or {}).get("in", 0) + (s.get("tokens") or {}).get("out", 0)
                     for s in model_calls)
        rows.append(
            f"<tr><td><code>{esc(phase['name'])}</code></td>"
            f"<td class='num'>{len(model_calls)}</td><td class='num'>{tokens:,}</td>"
            f"<td class='num'>{len(tool_calls)}</td><td class='num'>{len(writes)}</td>"
            f"<td class='num'>${cost:.4f}</td><td class='num'>{phase.get('latency_ms', 0):,} ms</td></tr>"
        )
    total_cost = sum(s.get("cost_usd", 0.0) for s in demo.steps)
    total_ms = sum(p.get("latency_ms", 0) for p in phases)
    rows.append(
        f"<tr><td><b>total</b></td>"
        f"<td class='num'>{len([s for s in demo.steps if s['kind'] == 'model_call'])}</td><td class='num'></td>"
        f"<td class='num'>{len([s for s in demo.steps if s['kind'] == 'tool_call'])}</td>"
        f"<td class='num'>{len([s for s in demo.steps if s['kind'] == 'tool_call' and s.get('risk') != 'read'])}</td>"
        f"<td class='num'>${total_cost:.4f}</td><td class='num'>{total_ms:,} ms</td></tr>"
    )
    return ("<table><thead><tr><th>phase</th><th class='num'>model calls</th><th class='num'>tokens</th>"
            "<th class='num'>tool calls</th><th class='num'>writes</th><th class='num'>cost</th>"
            "<th class='num'>wall</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def model_panel(traces: list[Trace]) -> str:
    if len(traces) < 2:
        return ('<p class="muted">Supply two or three traces of the same scenario with '
                "<code>--compare</code> to show that the dispositions do not depend on the model.</p>")
    tables = [t.dispositions for t in traces]
    keys = sorted({k for table in tables for k in table})
    rows = []
    disagreements = 0
    for key in keys:
        values = [table.get(key, {}).get("disposition", "—") for table in tables]
        agree = len(set(values)) == 1
        disagreements += 0 if agree else 1
        overridden = any(table.get(key, {}).get("source") == "policy" for table in tables)
        cell_class = "same" if agree else "diff"
        tds = "".join(f'<td class="{cell_class}">{esc(v)}</td>' for v in values)
        mark = '<span class="tag warn">policy</span>' if overridden else ""
        rows.append(f"<tr><td><code>{esc(key)}</code> {mark}</td>{tds}</tr>")
    head = "".join(f"<th>{esc(t.label)}</th>" for t in traces)
    verdict = (f'<p><span class="tag pass">identical</span> All {len(keys)} dispositions match across '
               f"{len(traces)} models, including the adversarial stub. The policy layer decides what gets "
               f"destroyed, not the model.</p>") if not disagreements else (
        f'<p><span class="tag fail">{disagreements} disagree</span> The models do not produce the same '
        f"disposition table. Every row marked in red is a decision the policy layer did not pin down.</p>")
    return verdict + ("<table><thead><tr><th>item</th>" + head + "</tr></thead><tbody>"
                      + "".join(rows) + "</tbody></table>")


def _stage_lines(step: dict) -> str:
    lines = []
    for field_name, label in STAGES:
        value = step.get(field_name)
        if value is None:
            continue
        if isinstance(value, dict):
            text = ", ".join(f"{k}={v}" for k, v in value.items())
        else:
            text = str(value)
        lines.append(f"<div><b>{esc(label)}</b> {esc(text)}</div>")
    status = (step.get("result") or {}).get("status")
    if status:
        lines.append(f"<div><b>result</b> {esc(status)}</div>")
    return f'<div class="stages">{"".join(lines)}</div>' if lines else ""


def _node(node: dict) -> str:
    bad = bool(node.get("failure_class") or node.get("error"))
    classes = "leaf" + (" bad" if bad else "")
    name_class = "gate" if node["kind"] == "gate" else ""
    risk = f' <span class="muted mono">[{esc(node["risk"])}]</span>' if node.get("risk") else ""
    flag = f' <span class="tag fail">{esc(node.get("failure_class") or "error")}</span>' if bad else ""
    label = (f'<span class="sid mono">s{node["step"]}</span>'
             f'<span class="kind mono">{esc(node["kind"])}</span>'
             f'<span class="{name_class}">{esc(node["name"])}</span>{risk}{flag}')
    stages = _stage_lines(node) if node["kind"] == "gate" else ""
    children = node.get("children") or []
    if not children:
        return f'<div class="{classes}" id="s{node["step"]}">{label}</div>{stages}'
    inner = "".join(_node(child) for child in children)
    return (f'<details id="s{node["step"]}" {"open" if node["kind"] in ("phase", "gate") else ""}>'
            f"<summary>{label}</summary>{stages}{inner}</details>")


def _finding_gist(step: dict) -> str:
    if step.get("note"):
        return str(step["note"])
    args = step.get("args") or {}
    pairs = [f"{k}={v}" for k, v in args.items() if not isinstance(v, (list, dict))]
    gist = ", ".join(pairs) or step.get("error") or ""
    return gist if len(gist) <= 120 else gist[:117] + "..."


def trace_explorer(demo: Optional[Trace]) -> str:
    if not demo or not demo.steps:
        return '<p class="muted">No demo trace was supplied. Pass one with <code>--trace</code>.</p>'
    pinned = "".join(
        f'<li><code>{esc(s.get("failure_class"))}</code> <a href="#s{s["step"]}">{esc(s["name"])}</a> '
        f'<span class="muted">{esc(_finding_gist(s))}</span></li>'
        for s in demo.findings)
    head = f'<div class="pin"><b>Findings</b><ul>{pinned}</ul></div>' if pinned else ""
    body = "".join(_node(root) for root in tree(demo.steps))
    return (head + '<div class="controls">'
            '<button onclick="toggleAll(\'#tree\', true)">expand all</button>'
            '<button onclick="toggleAll(\'#tree\', false)">collapse all</button></div>'
            f'<div class="tree" id="tree">{body}</div>')


def limitation_box(text: Optional[str]) -> str:
    if not text:
        return ('<div class="box todo"><b>Not written yet.</b> The honest limitation for this project goes in '
                "<code>DECISIONS.md</code> under <i>Brief facts</i>, on the line that starts "
                f"<code>{esc(LIMITATION_KEY)}</code>. It is rendered here verbatim.</div>")
    return f"<div class='box'><b>Limitation.</b> {esc(text)}</div>"


def render(results: dict, baseline: Optional[dict], demo: Optional[Trace],
           compare: list[Trace], limitation: Optional[str], mutants: Optional[dict] = None) -> str:
    sections = [
        ("Pass rate by failure class", per_class(results, baseline) + movement(results, baseline)),
        ("Every scenario, and what it asserted", scenario_rows(results, baseline)),
        ("Fault matrix", matrix_grid(results)),
        ("Would the suite notice a regression?", mutation_grid(mutants)),
        ("The demo run, step by step", trace_explorer(demo)),
        ("The same run under three models", model_panel(compare)),
        ("Cost and budget", cost_panel(demo, results)),
        ("What this does not do", limitation_box(limitation)),
    ]
    body = "".join(f"<section><h2>{esc(title)}</h2>{content}</section>" for title, content in sections)
    generated = esc(results.get("generated_at", ""))
    label = esc(results.get("label", "final"))
    mode = esc(results.get("mode", "twin"))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Offboard reliability scorecard</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>"
        "<h1>Offboard reliability scorecard</h1>"
        f"<p class='sub'>Run <code>{label}</code> against the <code>{mode}</code> drivers, {generated}. "
        "Every number on this page is read from a trace file, not from the agent's own account of itself.</p>"
        f"{header(results, baseline, demo, mutants)}{body}"
        f"<script>{JS}</script></div></body></html>"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="report.scorecard")
    parser.add_argument("--results", default=os.path.join(ROOT, "evals", "results", "final.json"))
    parser.add_argument("--baseline")
    parser.add_argument("--trace")
    parser.add_argument("--compare", nargs="*", default=[])
    parser.add_argument("--mutants")
    parser.add_argument("--decisions", default=os.path.join(ROOT, "DECISIONS.md"))
    parser.add_argument("--out", default=os.path.join(ROOT, "scorecard.html"))
    args = parser.parse_args(argv)

    if not os.path.exists(args.results):
        print(f"no results file at {args.results}; run `python -m evals.runner --label final` first")
        return 2
    results = load_results(args.results)
    baseline = load_results(args.baseline) if args.baseline and os.path.exists(args.baseline) else None
    demo = Trace("demo", args.trace, load_trace(args.trace)) if args.trace and os.path.exists(args.trace) else None
    compare = [Trace(_model_label(path), path, load_trace(path)) for path in args.compare if os.path.exists(path)]

    mutants = load_results(args.mutants) if args.mutants and os.path.exists(args.mutants) else None
    out = render(results, baseline, demo, compare, limitation_text(args.decisions), mutants)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {args.out} ({len(out) // 1024} KB)")
    return 0


def _model_label(path: str) -> str:
    steps = load_trace(path)
    for step in steps:
        if step["kind"] == "model_call" and step.get("model"):
            return str(step["model"])
    return re.sub(r"\.jsonl$", "", os.path.basename(path))


if __name__ == "__main__":
    raise SystemExit(main())
