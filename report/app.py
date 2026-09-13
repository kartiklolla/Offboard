from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

from report import console
from report.theme import CSS as THEME_CSS, FONTS
from twins.state import fixture_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LANDING_CSS = THEME_CSS + """
.hero { position:relative; padding:88px 0 72px; text-align:center }
.hero h1 { font-size:80px; letter-spacing:-1.6px; max-width:18ch; margin:0 auto }
.hero p { font-size:20px; color:var(--graphite); max-width:58ch; margin:24px auto 0 }
.hero .cta { display:flex; gap:12px; justify-content:center; margin-top:36px }
.hero .wash.a { width:520px; height:320px; left:8%; top:40px; background:linear-gradient(120deg, var(--coral), var(--sky)) }
.hero .wash.b { width:460px; height:300px; right:6%; top:120px; background:linear-gradient(120deg, var(--sky), var(--mint)) }
.hero > *:not(.wash) { position:relative }
section { padding:64px 0 0 }
section .eyebrow { margin-bottom:12px }
section h2 { max-width:24ch }
.lede { font-size:16px; color:var(--graphite); max-width:64ch; margin:16px 0 32px }
.flow { border:1px solid var(--ash); border-radius:40px; padding:32px; background:var(--paper); overflow:hidden }
.flow svg { width:100%; height:auto; display:block; font-family:var(--mono) }
.node { fill:var(--parchment); stroke:var(--ash) } .node.hub { fill:var(--periwinkle); stroke:none } .node.gate { fill:var(--offblack); stroke:none }
.node-t { font-size:18px; text-transform:uppercase; letter-spacing:-.4px; fill:var(--offblack) } .node-t.inv { fill:var(--parchment) }
.node-s { font-size:13px; fill:var(--graphite) } .node-s.inv { fill:var(--ash) }
.node-g rect { transition:fill .4s ease, filter .4s ease, stroke .4s ease }
.node-g.lit rect { fill:var(--periwinkle); stroke:transparent; filter:drop-shadow(-10px 0 18px var(--g1, var(--coral))) drop-shadow(10px 0 18px var(--g2, var(--sky))) }
.node-g.lit rect.hub { fill:var(--sky) } .node-g.lit rect.gate { fill:var(--offblack); filter:drop-shadow(0 0 22px var(--gold)) }
.node-g.lit .node-t { font-weight:500 }
.wire { fill:none; stroke:var(--ash); stroke-width:1.2 }
.flow-dot { fill:var(--lake); opacity:.9 }
.grid { display:grid; gap:12px } .grid.c2 { grid-template-columns:repeat(2,1fr) } .grid.c4 { grid-template-columns:repeat(4,1fr) }
.app h3 { display:flex; align-items:center; gap:12px } .app h3 svg { width:28px; height:28px; stroke:var(--offblack); fill:none; stroke-width:1.5 }
.app .steps { margin:18px 0 0; padding:0; list-style:none; display:flex; flex-direction:column; gap:8px }
.app .steps li { display:flex; gap:10px; align-items:baseline; font-size:13px; color:var(--graphite) } .app .steps li b { font-weight:500; color:var(--offblack); min-width:76px; text-transform:uppercase; font-size:11px; letter-spacing:-.033em }
.stages { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:24px }
.stage { border:1px solid var(--ash); border-radius:9999px; padding:14px 18px; background:var(--parchment) }
.stage b { display:block; font-weight:500; text-transform:uppercase; font-size:12px; letter-spacing:-.033em } .stage span { color:var(--graphite); font-size:12.5px }
.trap h3 { font-size:22px; margin-bottom:10px } .trap p { margin:0; color:var(--graphite); font-size:13.5px } .trap .tag { margin-top:14px }
.people.glow { --g1:var(--periwinkle); --g2:var(--mint) }
.people { display:flex; flex-direction:column; border:1px solid var(--ash); border-radius:24px; background:var(--paper); overflow:hidden }
.person { display:grid; grid-template-columns:minmax(0,2fr) minmax(0,2fr) minmax(0,1fr) auto; gap:16px; align-items:center; padding:16px 24px; border-bottom:1px solid var(--ash-soft) } .person:last-child { border-bottom:none }
.person .name { font-family:var(--serif); font-size:20px } .person .meta { color:var(--graphite); font-size:13px }
.person.leaving { background:var(--parchment) }
#plan { margin-top:24px; display:none } #plan.on { display:block }
#plan h3 { margin-bottom:6px } #plan .sub { color:var(--graphite); font-size:13px; margin:0 0 20px }
.write { display:grid; grid-template-columns:auto 1fr auto; gap:14px; align-items:center; padding:10px 0; border-bottom:1px solid rgba(36,36,36,.12) } .write:last-child { border-bottom:none }
.write input { width:18px; height:18px; accent-color:var(--offblack) }
.write .d { font-size:13px; min-width:0; overflow-wrap:anywhere } .write .d small { display:block; color:var(--graphite); font-size:12px; margin-top:2px }
.write.off .d { text-decoration:line-through; color:var(--smoke) }
.esc { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 22px }
.apply { display:flex; align-items:center; gap:16px; margin-top:24px; flex-wrap:wrap } .apply .note { font-size:12.5px; color:var(--graphite) }
.busy { color:var(--graphite); font-size:13px; display:flex; gap:10px; align-items:center }
footer { margin-top:96px; border-top:1px solid var(--ash); padding-top:24px; display:flex; justify-content:space-between; color:var(--smoke); font-size:12px; flex-wrap:wrap; gap:12px }
@media (max-width:900px) { .hero h1 { font-size:44px } .hero p { font-size:16px } .grid.c2, .grid.c4 { grid-template-columns:1fr } .stages { grid-template-columns:1fr } .person { grid-template-columns:1fr; gap:6px } .hero .wash { display:none } }
"""

ICONS = {
    "github": "<svg viewBox='0 0 24 24'><circle cx='6' cy='5' r='2.5'/><circle cx='6' cy='19' r='2.5'/><circle cx='18' cy='8' r='2.5'/><path d='M6 7.5v9M18 10.5c0 4-4 4-8 5.5'/></svg>",
    "slack": "<svg viewBox='0 0 24 24'><path d='M9 3v18M15 3v18M3 9h18M3 15h18'/></svg>",
    "drive": "<svg viewBox='0 0 24 24'><path d='M3 8.5A1.5 1.5 0 0 1 4.5 7H9l2 2h8.5A1.5 1.5 0 0 1 21 10.5v7A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z'/></svg>",
    "sheets": "<svg viewBox='0 0 24 24'><rect x='4' y='4' width='16' height='16' rx='2'/><path d='M4 10h16M4 15h16M10 4v16'/></svg>",
}


APP_NODES = [("github", "GitHub", "org · repos · deploy keys"), ("slack", "Slack", "account · channels"), ("drive", "Drive", "owned files · shares"), ("sheets", "Sheets", "evidence log")]
CHAIN_NODES = [("resolve", "Resolve identity", "two signals or abstain", "hub"), ("inventory", "Inventory", "deterministic, paginated", ""),
               ("classify", "Classify", "model proposes, policy decides", ""), ("gate", "Gate", "five stages, every write", "gate"), ("report", "Report", "evidence + cited summary", "")]


def flow_svg() -> str:
    aw, ah, ay = 290, 68, 24
    cw, ch, cy, gap = 280, 68, 300, 12
    app_x = [70 + i * 340 for i in range(4)]
    chain_x = [20 + i * (cw + gap) for i in range(5)]
    rx0 = chain_x[0] + cw / 2
    parts = []
    for (key, _, _), x in zip(APP_NODES, app_x):
        cx = x + aw / 2
        parts.append(f"<path id='route-{key}' class='wire' d='M{cx} {ay+ah} C {cx} {ay+ah+110}, {rx0} {cy-120}, {rx0} {cy}'/>")
    parts.append(f"<path id='route-chain' class='wire' d='M{chain_x[0]+cw} {cy+ch/2} L {chain_x[-1]} {cy+ch/2}'/>")
    parts.append("<circle id='flow-dot' class='flow-dot' r='7' cx='-20' cy='-20'/>")

    def node(x: float, y: float, w: float, h: float, key: str, title: str, sub: str, cls: str = "") -> str:
        inv = " inv" if cls == "gate" else ""
        return (f"<g class='node-g' data-node='{key}'><rect class='node {cls}' x='{x}' y='{y}' width='{w}' height='{h}' rx='{h/2}'/>"
                f"<text class='node-t{inv}' x='{x+26}' y='{y+29}'>{title}</text><text class='node-s{inv}' x='{x+26}' y='{y+51}'>{sub}</text></g>")

    for (key, title, sub), x in zip(APP_NODES, app_x):
        parts.append(node(x, ay, aw, ah, key, title, sub))
    for (key, title, sub, cls), x in zip(CHAIN_NODES, chain_x):
        parts.append(node(x, cy, cw, ch, key, title, sub, cls))
    parts.append(f"<text class='node-s' x='{chain_x[3]}' y='{cy+ch+34}'>precondition → diff → approval → apply → read-back</text>")
    return f"<svg id='flow' viewBox='0 0 {chain_x[-1]+cw+20} 420' role='img' aria-label='Offboard pipeline: four apps feed identity resolution, inventory, classification, the gate and the report'>" + "".join(parts) + "</svg>"


FLOW_JS = """
(function () {
  const svg = document.getElementById('flow'); if (!svg) return;
  const dot = svg.querySelector('#flow-dot');
  const nodes = {}; svg.querySelectorAll('.node-g').forEach(g => nodes[g.dataset.node] = g);
  const apps = ['github', 'slack', 'drive', 'sheets'];
  const chain = ['resolve', 'inventory', 'classify', 'gate', 'report'];
  const chainPath = svg.querySelector('#route-chain');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let lit = null, last = null;
  function light(key) { if (lit) lit.classList.remove('lit'); lit = key ? nodes[key] : null; if (lit) lit.classList.add('lit'); }
  function at(path, t) { const p = path.getPointAtLength(path.getTotalLength() * t); dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y); }
  const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2) / 2;
  function travel(path, from, to, ms) { return new Promise(res => { const t0 = performance.now(); function f(now) { const k = Math.min(1, (now - t0) / ms); at(path, from + (to - from) * ease(k)); if (k < 1) requestAnimationFrame(f); else res(); } requestAnimationFrame(f); }); }
  const wait = ms => new Promise(r => setTimeout(r, ms));
  function nodeCenterT(key) { const r = nodes[key].querySelector('rect'); const cx = +r.getAttribute('x') + (+r.getAttribute('width')) / 2; const L = chainPath.getTotalLength(); const x0 = chainPath.getPointAtLength(0).x; const x1 = chainPath.getPointAtLength(L).x; return Math.max(0, Math.min(1, (cx - x0) / (x1 - x0))); }
  async function cycle() {
    let app = apps[Math.floor(Math.random() * apps.length)]; if (app === last) app = apps[(apps.indexOf(app) + 1) % apps.length]; last = app;
    const route = svg.querySelector('#route-' + app);
    at(route, 0); light(app); await wait(900);
    await travel(route, 0, 1, 1500);
    for (let i = 0; i < chain.length; i++) {
      const key = chain[i]; light(key);
      if (i < chain.length - 1) { await wait(800); await travel(chainPath, nodeCenterT(key), nodeCenterT(chain[i + 1]), 1100); }
    }
    await wait(1200); light(null); await wait(400); cycle();
  }
  if (reduce) { light('gate'); at(chainPath, nodeCenterT('gate')); } else cycle();
})();
"""


def landing_html(mode: str, model: str, scorecard: Optional[str]) -> str:
    score = f"<a class='btn small' href='{scorecard}'>Scorecard</a>" if scorecard else ""
    apps = [
        ("github", "GitHub", ["Org membership, every repo collaboration, every deploy key, paginated with a count check.", "Keys named in a workflow file are escalated, not deleted.", "Collaborator removals before the org removal; each read back before it counts."]),
        ("slack", "Slack", ["Account plus every channel membership, private ones included.", "Two identity signals required; <code>@dhruv.m</code> is never <code>@dhruv</code>.", "Kicks are reversible and go first; deactivation is last, or escalated when the plan cannot."]),
        ("drive", "Google Drive", ["Files the person owns, files shared to them, external shares.", "Owned files transfer to the manager before the person is removed; nothing is orphaned.", "External shares are escalated to a human."]),
        ("sheets", "Google Sheets", ["The evidence log: one row per gated write with status, diff and undo record.", "Written through the same gate as everything else.", "This is what the auditor asks for."]),
    ]
    app_cards = "".join(
        f"<div class='card lg app glow'><h3><span class='dot {k}'></span>{ICONS[k]}{n}</h3><ul class='steps'>"
        f"<li><b>Read</b><span>{a}</span></li><li><b>Decide</b><span>{b}</span></li><li><b>Write</b><span>{c}</span></li></ul></div>"
        for k, n, (a, b, c) in apps
    )
    traps = [
        ("Dependency", "billing-runbooks is owned by the leaver and shared with four colleagues. Revoke it and the folder is orphaned. Offboard transfers ownership first, then removes the leaver.", "F2"),
        ("Shared credential", "Deploy key dmehta-laptop looks personal. A workflow file still uses it. Deleting it breaks staging. Offboard escalates it and makes zero destructive calls.", "F3"),
        ("Identity", "@dhruv and @dhruv.m, one character apart, the second with no email. Offboard needs two independent signals; with one it abstains for that app.", "F1"),
        ("Injection", "Three planted notes tell the agent this account is exempt. Each is logged as a finding. None changes a disposition, even with a model that obeys them.", "F7"),
    ]
    trap_cards = "".join(f"<div class='card lg trap glow'><h3>{t}</h3><p>{d}</p><span class='tag {c}'>{c}</span></div>" for t, d, c in traps)
    stages = [("Precondition", "read the current state; nothing to do is a result, not an error"), ("Diff", "the exact change, as text, before anything moves"),
              ("Approval", "irreversible actions need a token; a plan file the human edited"), ("Apply", "one attempt; failures escalate, never retry"),
              ("Read-back", "a 200 that changed nothing is a failure, class F5")]
    stage_html = "".join(f"<div class='stage glow'><b>{i+1} · {n}</b><span>{d}</span></div>" for i, (n, d) in enumerate(stages))
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
{FONTS}<title>Offboard</title><style>{LANDING_CSS}</style></head><body>
<div class="wrap">
<nav class="nav">
  <a class="brand" href="#"><i></i>Offboard</a>
  <div class="links"><a href="#how">How it works</a><a href="#apps">Apps</a><a href="#traps">Traps</a><a href="#evidence">Evidence</a><a href="#run">Run</a></div>
  <div class="actions">{score}<a class="btn small black" href="/console">Console</a></div>
</nav>

<header class="hero">
  <div class="wash a"></div><div class="wash b"></div>
  <p class="eyebrow"><span class="dot"></span>An agent for the day someone leaves</p>
  <h1>Revoke access. Prove it. Undo it.</h1>
  <p>Offboard walks GitHub, Slack, Google Drive and Sheets for a departing employee, decides what to transfer, revoke or escalate, and passes every write through a five-stage gate. The model proposes; a policy layer decides; one trace file records all of it.</p>
  <div class="cta"><a class="btn blue" href="#run">Start an offboarding ▸</a><a class="btn" href="#how">How it works</a></div>
</header>

<section id="how">
  <p class="eyebrow"><span class="dot"></span>How it works</p>
  <h2>Deterministic code enumerates. The model classifies. Policy decides. The gate writes.</h2>
  <p class="lede">Nothing the model says reaches an API directly. Enumeration is paginated code with a count check, so a dropped page is caught. Every disposition the model proposes is checked against rules that never read content from the apps. Every write is preconditioned, diffed, approved, applied and read back.</p>
  <div class="flow">{flow_svg()}</div>
  <div class="stages">{stage_html}</div>
</section>

<section id="apps">
  <p class="eyebrow"><span class="dot"></span>Inside each app</p>
  <h2>Four apps, one interface, twin or live.</h2>
  <p class="lede">Each driver exists twice: a deterministic twin with fault injection for the evaluation suite, and a live client for the real API. Same methods, one flag.</p>
  <div class="grid c2">{app_cards}</div>
</section>

<section id="traps">
  <p class="eyebrow"><span class="dot"></span>The four traps</p>
  <h2>Seeded into the fixture because a naive agent gets each one wrong.</h2>
  <div class="grid c4" style="margin-top:32px">{trap_cards}</div>
</section>

<section id="evidence">
  <p class="eyebrow"><span class="dot"></span>Evaluation</p>
  <h2>A harness that would notice if a defence went missing.</h2>
  <div class="grid c4" style="margin-top:32px">
    <div class="stat glow"><b>28</b><span>scenarios, one failure class each</span></div>
    <div class="stat glow"><b>27</b><span>fault-matrix cells, invariants only</span></div>
    <div class="stat glow"><b>11</b><span>mutants removed, eleven caught</span></div>
    <div class="stat glow"><b>8</b><span>named failure classes, F1 to F8</span></div>
  </div>
</section>

<section id="run">
  <p class="eyebrow"><span class="dot"></span>Run</p>
  <h2>Choose who is leaving.</h2>
  <p class="lede">Planning is a dry run: every diff, nothing applied. You untick what you are not sure about. Apply executes only what is still ticked, through the gate, and the console opens as it happens. Mode: <b>{mode}</b> · model: <b>{model}</b>.</p>
  <div class="people glow" id="people"><div class="person"><span class="smoke">loading directory…</span></div></div>
  <div class="card lg peri" id="plan"></div>
</section>

<footer><span>Offboard · Multi-App AI Agent Hackathon, 13 September 2026 · Kartik Lolla, Sanjib Behera</span><span>Twins are a test rig, not a production mirror. Every page reads the same trace file.</span></footer>
</div>
<script>
{FLOW_JS}
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
let PLAN = null;
async function people() {{
  try {{
    const r = await fetch('/people'); const ps = await r.json();
    $('#people').innerHTML = ps.map(p => `<div class="person ${{p.status==='leaving'?'leaving':''}}">
      <div><div class="name">${{esc(p.name)}}</div><div class="meta">${{esc(p.email)}}</div></div>
      <div class="meta">${{esc(p.title||'')}}${{p.team?' · '+esc(p.team):''}}</div>
      <div>${{p.status==='leaving'?'<span class="tag needs_approval">last day today</span>':'<span class="tag">active</span>'}}</div>
      <div><button class="btn small ${{p.status==='leaving'?'black':''}}" data-email="${{esc(p.email)}}">Plan offboarding</button></div></div>`).join('');
    document.querySelectorAll('.person button').forEach(b => b.onclick = () => plan(b.dataset.email, b));
  }} catch (e) {{ $('#people').innerHTML = `<div class="person"><span class="smoke">start the server to load the directory: python -m report.app --serve 8765</span></div>`; }}
}}
async function plan(email, btn) {{
  btn.disabled = true; const label = btn.textContent; btn.textContent = 'Planning…';
  const box = $('#plan'); box.className = 'card lg peri on'; box.innerHTML = `<div class="busy"><span class="pulse"></span> dry run for ${{esc(email)}}: enumerating, classifying, producing every diff…</div>`;
  try {{
    const r = await fetch('/plan', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{user: email}})}});
    if (!r.ok) throw new Error(await r.text());
    PLAN = await r.json(); renderPlan();
  }} catch (e) {{ box.innerHTML = `<h3>Plan failed</h3><p class="sub">${{esc(e.message)}}</p>`; }}
  btn.disabled = false; btn.textContent = label;
}}
function renderPlan() {{
  const box = $('#plan'); const acts = PLAN.actions; const esc_ = PLAN.escalated || [];
  const irr = acts.filter(a => a.risk === 'irreversible').length;
  box.innerHTML = `<h3>${{acts.length}} writes planned for ${{esc(PLAN.target)}}, ${{irr}} irreversible, nothing applied yet.</h3>
    <p class="sub">Untick anything you are not sure about. Escalated items below need a human and will not be touched.</p>
    <div class="esc">${{esc_.map(e => `<span class="tag escalate wrap" title="${{esc(e.reason)}}">escalated · ${{esc(e.key.split(':').slice(2).join(':'))}}</span>`).join('') || '<span class="smoke">no escalations</span>'}}</div>
    <div id="writes">${{acts.map((a,i) => `<label class="write ${{a.approved?'':'off'}}"><input type="checkbox" data-i="${{i}}" ${{a.approved?'checked':''}}><span class="d">${{esc(a.name)}}<small>${{esc(a.diff||'')}}</small></span><span class="tag ${{esc(a.risk)}}">${{esc(a.risk)}}</span></label>`).join('')}}</div>
    <div class="apply"><button class="btn blue" id="applyBtn">Apply ${{acts.filter(a=>a.approved).length}} writes ▸</button><span class="note">Each one goes through the gate; the console opens live. Unticked lines stop at the gate as <b>needs_approval</b>.</span></div>`;
  box.querySelectorAll('input').forEach(cb => cb.onchange = () => {{ PLAN.actions[+cb.dataset.i].approved = cb.checked; renderPlan(); }});
  $('#applyBtn').onclick = apply;
}}
async function apply() {{
  const n = PLAN.actions.filter(a => a.approved).length;
  if (!confirm(`Apply ${{n}} writes for ${{PLAN.target}} in ${{'{mode}'}} mode? Irreversible actions will run.`)) return;
  $('#applyBtn').disabled = true; $('#applyBtn').textContent = 'Applying…';
  const r = await fetch('/apply', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(PLAN)}});
  if (!r.ok) {{ alert(await r.text()); $('#applyBtn').disabled = false; return; }}
  location.href = '/console';
}}
people();
</script>
</body></html>"""


class App:
    def __init__(self, mode: str, model: str, hr: Optional[str], trace: str, scorecard: Optional[str], seed: str = "acme") -> None:
        self.mode, self.model, self.hr, self.trace, self.scorecard, self.seed = mode, model, hr, trace, scorecard, seed
        self.plan_path = os.path.join(ROOT, "plan.json")
        self.lock = threading.Lock()
        self.landing = landing_html(mode, model, scorecard).encode("utf-8")
        links = f"<a class='btn small black' href='{scorecard}'>Scorecard</a>" if scorecard else ""
        self.console_page = console.page(None, "Offboard · run console", links).encode("utf-8")

    def people(self) -> list[dict]:
        path = self.hr or fixture_path(self.seed)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data["people"] if isinstance(data, dict) else data

    def cli(self, *args: str) -> list[str]:
        cmd = [sys.executable, os.path.join(ROOT, "cli.py"), *args, "--mode", self.mode, "--model", self.model]
        if self.hr:
            cmd += ["--hr", self.hr]
        return cmd

    def plan(self, user: str) -> dict:
        with self.lock:
            proc = subprocess.run(self.cli("plan", "--user", user, "--out", self.plan_path, "--trace", os.path.join(ROOT, "traces", "plan.jsonl")), cwd=ROOT, capture_output=True, text=True, timeout=600)
            if proc.returncode not in (0, 2) or not os.path.exists(self.plan_path):
                raise RuntimeError((proc.stdout + proc.stderr)[-1500:])
            with open(self.plan_path, encoding="utf-8") as fh:
                return json.load(fh)

    def apply(self, plan: dict) -> None:
        with self.lock:
            with open(self.plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh, indent=2)
            if os.path.exists(self.trace):
                os.remove(self.trace)
            subprocess.Popen(self.cli("apply", "--plan", self.plan_path, "--trace", self.trace), cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(app: App, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", extra: Optional[dict] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, app.landing)
            if path == "/console":
                return self._send(200, app.console_page)
            if path == "/trace.jsonl":
                body = b""
                if os.path.exists(app.trace):
                    with open(app.trace, "rb") as fh:
                        body = fh.read()
                return self._send(200, body, "application/x-ndjson; charset=utf-8", {"X-Trace-Path": os.path.relpath(app.trace, ROOT)})
            if path == "/people":
                return self._send(200, json.dumps(app.people()).encode(), "application/json")
            if app.scorecard and path == "/" + app.scorecard.lstrip("/") and os.path.exists(os.path.join(ROOT, app.scorecard)):
                with open(os.path.join(ROOT, app.scorecard), "rb") as fh:
                    return self._send(200, fh.read())
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            payload: Any = json.loads(self.rfile.read(length) or b"{}")
            try:
                if path == "/plan":
                    return self._send(200, json.dumps(app.plan(payload["user"])).encode(), "application/json")
                if path == "/apply":
                    app.apply(payload)
                    return self._send(200, b'{"ok": true}', "application/json")
            except Exception as exc:
                return self._send(500, str(exc).encode(), "text/plain; charset=utf-8")
            self._send(404, b"not found", "text/plain")

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stdout.write(f"offboard: http://127.0.0.1:{port}/  mode={app.mode} model={app.model} trace={app.trace}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m report.app", description="Landing page, plan/apply flow and live console in one local server.")
    p.add_argument("--serve", type=int, default=8765, metavar="PORT")
    p.add_argument("--mode", choices=("twin", "live"), default="twin")
    p.add_argument("--model", default="heuristic")
    p.add_argument("--hr", help="HR directory JSON for live mode")
    p.add_argument("--trace", default=os.path.join(ROOT, "traces", "run.jsonl"))
    p.add_argument("--scorecard", help="relative path to scorecard.html, served and linked")
    p.add_argument("--out", help="write the landing page as a static file instead of serving")
    args = p.parse_args(argv)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(landing_html(args.mode, args.model, args.scorecard))
        sys.stdout.write(f"landing: {args.out}\n")
        return 0
    serve(App(args.mode, args.model, args.hr, args.trace, args.scorecard), args.serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
