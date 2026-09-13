from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

CSS = """
:root { --ink:#14161a; --muted:#5b6472; --line:#e2e5ea; --bg:#ffffff; --panel:#f7f8fa; --soft:#eef0f4;
  --pass:#1a7f4b; --pass-bg:#e7f4ec; --fail:#b3261e; --fail-bg:#fdeceb; --warn:#8a6100; --warn-bg:#fdf3df; --accent:#2f4fd8; --accent-bg:#e9edfc; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --ink:#e8eaee; --muted:#98a2b3; --line:#2b3038; --bg:#14161a; --panel:#1b1e24; --soft:#22262e;
  --pass:#4ac286; --pass-bg:#14301f; --fail:#f2867d; --fail-bg:#331816; --warn:#e0b25c; --warn-bg:#2e2512; --accent:#8aa0ff; --accent-bg:#1c2340; } }
:root[data-theme="dark"] { --ink:#e8eaee; --muted:#98a2b3; --line:#2b3038; --bg:#14161a; --panel:#1b1e24; --soft:#22262e;
  --pass:#4ac286; --pass-bg:#14301f; --fail:#f2867d; --fail-bg:#331816; --warn:#e0b25c; --warn-bg:#2e2512; --accent:#8aa0ff; --accent-bg:#1c2340; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
.wrap { max-width:1240px; margin:0 auto; padding:28px 24px 80px; }
h1 { font-size:24px; margin:0; letter-spacing:-.01em }
h2 { font-size:15px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:36px 0 12px; font-weight:600 }
.mono, code, .diff { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12.5px }
.muted { color:var(--muted) }
.head { display:flex; flex-wrap:wrap; align-items:baseline; gap:10px 18px; }
.pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; border:1px solid var(--line); background:var(--soft); vertical-align:middle }
.pill.clean, .pill.applied, .pill.resolved { background:var(--pass-bg); color:var(--pass); border-color:transparent }
.pill.dirty, .pill.failed_apply, .pill.failed_postcondition { background:var(--fail-bg); color:var(--fail); border-color:transparent }
.pill.needs_human, .pill.needs_approval, .pill.blocked_precondition, .pill.escalate { background:var(--warn-bg); color:var(--warn); border-color:transparent }
.pill.dry_run, .pill.skipped_dry_run, .pill.running { background:var(--accent-bg); color:var(--accent); border-color:transparent }
.pill.F1,.pill.F2,.pill.F3,.pill.F4,.pill.F5,.pill.F6,.pill.F7,.pill.F8 { background:var(--fail-bg); color:var(--fail); border-color:transparent; font-family:ui-monospace,monospace }
.pill.rule { font-family:ui-monospace,monospace; font-weight:500 }
.counts { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-top:16px }
.count { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px }
.count b { display:block; font-size:22px; font-variant-numeric:tabular-nums; line-height:1.1 }
.count span { font-size:12px; color:var(--muted) }
.phases { display:grid; grid-template-columns:repeat(6,1fr); gap:6px }
.phase { background:var(--panel); border:1px solid var(--line); border-top:3px solid var(--line); border-radius:6px; padding:8px 10px; font-size:12.5px }
.phase.done { border-top-color:var(--pass) } .phase.open { border-top-color:var(--accent); animation:pulse 1.2s infinite }
.phase b { display:block; font-weight:600 } .phase span { color:var(--muted) }
@keyframes pulse { 0%,100% { box-shadow:0 0 0 0 transparent } 50% { box-shadow:0 0 0 3px var(--accent-bg) } }
@media (prefers-reduced-motion: reduce) { .phase.open { animation:none } }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:10px }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px }
.card h3 { margin:0 0 6px; font-size:14px; display:flex; justify-content:space-between; align-items:center }
.card .row { display:flex; justify-content:space-between; gap:8px; font-size:13px; padding:2px 0 }
.tablewrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel) }
table { border-collapse:collapse; width:100%; font-size:13px }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top }
th { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); background:var(--soft) }
tr:last-child td { border-bottom:none }
tr.trap td:first-child { border-left:3px solid var(--accent) }
.filters { display:flex; gap:6px; margin-bottom:10px; flex-wrap:wrap }
.filters button { border:1px solid var(--line); background:var(--panel); color:var(--ink); border-radius:999px; padding:3px 10px; font-size:12px; cursor:pointer }
.filters button.on { background:var(--accent); color:#fff; border-color:var(--accent) }
.filters button:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
.gate { border:1px solid var(--line); border-left:4px solid var(--line); border-radius:8px; background:var(--panel); margin:6px 0 }
.gate.applied { border-left-color:var(--pass) } .gate.failed_apply, .gate.failed_postcondition { border-left-color:var(--fail) }
.gate.needs_approval, .gate.blocked_precondition { border-left-color:var(--warn) } .gate.skipped_dry_run { border-left-color:var(--accent) }
.gate summary { list-style:none; cursor:pointer; padding:9px 12px; display:flex; gap:10px; align-items:center; flex-wrap:wrap }
.gate summary::-webkit-details-marker { display:none }
.gate summary .n { color:var(--muted); font-family:ui-monospace,monospace; font-size:12px; min-width:40px }
.gate summary .name { font-weight:600 }
.gate summary .diff { color:var(--muted); flex:1; min-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.gate .body { padding:0 12px 12px 62px; display:grid; grid-template-columns:130px 1fr; gap:4px 12px; font-size:12.5px }
.gate .body .k { color:var(--muted) }
.gate .calls { grid-column:1 / -1; margin-top:6px; border-top:1px dashed var(--line); padding-top:6px }
.gate .calls div { font-family:ui-monospace,monospace; font-size:12px; color:var(--muted) }
.gate .calls .err { color:var(--fail) }
.skipped { padding:6px 12px 6px 16px; color:var(--muted); font-size:12.5px; border-left:4px solid var(--line); margin:4px 0 }
.findings { display:flex; flex-direction:column; gap:6px }
.finding { display:flex; gap:10px; align-items:baseline; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px 12px; font-size:13px }
.finding .n { color:var(--muted); font-family:ui-monospace,monospace; font-size:12px }
.summary p { margin:6px 0; padding:8px 12px; background:var(--panel); border:1px solid var(--line); border-radius:8px }
.summary p.dropped { text-decoration:line-through; color:var(--muted) } .summary p.dropped small { text-decoration:none; display:block; color:var(--fail); margin-top:2px }
.summary a { color:var(--accent); text-decoration:none; font-family:ui-monospace,monospace }
.undo li { font-family:ui-monospace,monospace; font-size:12.5px; margin:3px 0 }
.undo .no { color:var(--warn) }
.empty { color:var(--muted); font-style:italic; padding:8px 0 }
.live { font-size:12px; color:var(--muted) } .live b.on { color:var(--pass) }
:target { outline:2px solid var(--accent); outline-offset:2px }
@media (max-width:800px) { .phases { grid-template-columns:repeat(3,1fr) } .gate .body { grid-template-columns:1fr; padding-left:12px } }
"""

JS = r"""
const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pill = (t, cls) => `<span class="pill ${esc(cls||t)}">${esc(t)}</span>`;
const TRAPS = ['drive:folder:billing-runbooks','github:deploy_key:dmehta-laptop','slack:user:slack_account','drive:file:IT Offboarding Notes','slack:channel_member:#deploys','github:repo_collaborator:acme/legacy-billing'];
let FILTER = 'all';

function parseJsonl(text){ const out=[]; for (const line of text.split('\n')) { if (!line.trim()) continue; try { out.push(JSON.parse(line)); } catch(e) {} } return out; }

function render(steps){
  const byId = {}; steps.forEach(s => byId[s.step] = s);
  const kind = k => steps.filter(s => s.kind === k);
  const run = kind('run')[0]; const status = kind('run_status').slice(-1)[0];
  const gates = kind('gate'); const writes = gates.filter(g => /^(transfer|revoke|undo):/.test(g.name));
  const findings = steps.filter(s => s.failure_class);
  const cost = steps.reduce((a,s)=>a+(s.cost_usd||0),0);
  const ms = steps.reduce((a,s)=>a+(s.latency_ms||0),0);
  const target = run ? run.name.split(':').slice(1).join(':') : (steps[0]||{}).run_id || '';
  const mode = (run&&run.args&&run.args.mode) || (steps[0]||{}).mode || '';
  const model = run && run.args ? run.args.model : '';
  const st = status ? status.name : (steps.length ? 'running' : 'waiting');
  $('#head').innerHTML = `<h1>${esc(target||'no trace yet')}</h1> ${pill(st)} <span class="muted">${esc(mode)}${model?' · model '+esc(model):''}${run?' · run '+esc(run.run_id):''}</span>`;
  const items = kind('inventory').find(s=>s.name==='all'); const disps = kind('disposition');
  const esc_ = disps.filter(d=>['escalate','needs_human'].includes(d.result.disposition)).length;
  const applied = writes.filter(g=>g.result&&g.result.status==='applied').length;
  const failed = writes.filter(g=>g.result&&/^failed/.test(g.result.status)).length;
  $('#counts').innerHTML = [
    [items?items.result.count:disps.length,'access items'],[writes.length,'writes gated'],[applied,'applied'],[failed,'failed'],[esc_,'escalated'],
    [findings.length,'findings'],[kind('model_call').length,'model calls'],[kind('tool_call').length,'tool calls'],['$'+cost.toFixed(4),'model cost'],[(ms/1000).toFixed(1)+'s','wall time']
  ].map(([b,l])=>`<div class="count"><b>${esc(b)}</b><span>${esc(l)}</span></div>`).join('');

  const phaseNames = ['resolve_identity','inventory','classify','plan','execute','report'];
  const phases = kind('phase'); const open = steps.length && !status ? phaseNames.filter(p=>!phases.some(x=>x.name===p))[0] : null;
  $('#phases').innerHTML = phaseNames.map(p => { const ph = phases.find(x=>x.name===p); const children = steps.filter(s=>s.parent===(ph||{}).step).length;
    return `<div class="phase ${ph?'done':(p===open?'open':'')}"><b>${esc(p.replace('_',' '))}</b><span>${ph?children+' steps · '+ph.latency_ms+' ms':(p===open?'running…':'')}</span></div>`; }).join('');

  const ids = kind('identity'); const idOv = findings.filter(f=>f.name.startsWith('override:identity:'));
  $('#identity').innerHTML = ids.length ? `<div class="cards">${ids.map(i => { const r=i.result; const ov = idOv.find(f=>f.name.endsWith(':'+i.name));
    return `<div class="card" id="s${i.step}"><h3>${esc(i.name)} ${pill(r.status)}</h3>
      <div class="row"><span class="muted">principal</span><span class="mono">${esc(r.principal_id||'—')}</span></div>
      <div class="row"><span class="muted">display</span><span>${esc(r.display)}</span></div>
      <div class="row"><span class="muted">signals</span><span>${(r.signals||[]).map(s=>pill(s,'rule')).join(' ')||'<span class="muted">none</span>'}</span></div>
      ${ov?`<div class="row"><span class="muted">model said</span><span><span class="mono">${esc(ov.args.model_said||'nothing')}</span> ${pill('F1')} overridden</span></div>`:`<div class="row"><span class="muted">model</span><span>agreed (${esc(r.model_said||'—')})</span></div>`}
    </div>`; }).join('')}</div>` : '<div class="empty">no identity events yet</div>';

  const inj = findings.filter(f=>f.name.startsWith('injection:')); const ovs = findings.filter(f=>f.name.startsWith('override:')&&!f.name.startsWith('override:identity')&&f.name!=='override:order');
  const apps = ['all', ...new Set(disps.map(d=>d.name.split(':')[0]))];
  $('#filters').innerHTML = apps.map(a=>`<button class="${a===FILTER?'on':''}" data-app="${esc(a)}">${esc(a)}</button>`).join('');
  $('#filters').querySelectorAll('button').forEach(b=>b.onclick=()=>{FILTER=b.dataset.app; render(steps);});
  const rows = disps.filter(d=>FILTER==='all'||d.name.startsWith(FILTER+':')).map(d => { const r=d.result; const [app,kind_,...rest]=d.name.split(':'); const res=rest.join(':');
    const ov = ovs.find(f=>f.name==='override:'+d.name); const ij = inj.find(f=>f.args&&f.args.item_key===d.name);
    return `<tr class="${TRAPS.includes(d.name)?'trap':''}" id="s${d.step}"><td class="mono">${esc(res)}</td><td>${esc(app)}</td><td>${esc(kind_)}</td>
      <td>${pill(r.disposition)}${r.transfer_to?` <span class="muted">→ ${esc(r.transfer_to)}</span>`:''}</td>
      <td>${r.rule?pill(r.rule,'rule'):''} <span class="muted">${esc(r.source)}</span>${ov?` ${pill(ov.failure_class)} <span class="muted">model said ${esc(ov.args.model_said)}</span>`:''}</td>
      <td>${ij?pill('injection','F7')+' <span class="muted">'+esc(ij.args.field)+'</span>':''}</td><td class="muted">${esc(r.reason)}</td></tr>`; }).join('');
  $('#inventory').innerHTML = disps.length ? `<div class="tablewrap"><table><thead><tr><th>resource</th><th>app</th><th>kind</th><th>disposition</th><th>rule · source</th><th>content</th><th>reason</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">no dispositions yet</div>';

  const plan = kind('plan').find(p=>p.name==='actions'); const order = plan ? plan.result.order : gates.map(g=>g.name);
  const skipped = kind('skipped');
  const stage = (k,v) => v===undefined||v===null ? '' : `<div class="k">${k}</div><div>${v}</div>`;
  const gateHtml = g => { const s = g.result?g.result.status:'running'; const calls = steps.filter(c=>c.parent===g.step&&c.kind==='tool_call');
    const undo = g.undo||{};
    return `<details class="gate ${esc(s)}" id="s${g.step}" ${/^failed|needs_approval/.test(s)?'open':''}><summary><span class="n">s${g.step}</span><span class="name">${esc(g.name)}</span>${pill(s)}<span class="pill">${esc(g.risk)}</span><span class="diff">${esc(g.dry_run||'')}</span></summary>
      <div class="body">
        ${stage('1 precondition', g.precondition?`${g.precondition.ok?'ok':'false'} <span class="muted mono">${esc(JSON.stringify(g.precondition.value))}</span>`:undefined)}
        ${stage('2 diff', g.dry_run?`<span class="diff">${esc(g.dry_run)}</span>`:undefined)}
        ${stage('3 approval', g.approval?`${g.approval.granted?'granted':'not granted'} <span class="muted mono">${esc(g.approval.key)}${g.approval.strict?' · strict':''}</span>`:undefined)}
        ${stage('4 apply', g.result?(g.error?`<span class="err mono">${esc(g.error)}</span>`:(['applied','failed_postcondition'].includes(s)?'called':'not called')):undefined)}
        ${stage('5 read-back', g.postcondition?`${g.postcondition.ok?'confirmed':'<b>not confirmed</b>'} <span class="muted">after ${g.postcondition.attempts} read${g.postcondition.attempts>1?'s':''}</span>${g.failure_class?' '+pill(g.failure_class):''}`:undefined)}
        ${stage('undo', undo.op?`<span class="mono">${esc(undo.op)} ${esc(JSON.stringify(undo.args))}</span> ${undo.supported===false?'<span class="pill needs_human">not supported</span> <span class="muted">'+esc(undo.note||'')+'</span>':''}`:undefined)}
        ${stage('note', g.note)}
        ${calls.length?`<div class="calls">${calls.map(c=>`<div class="${c.error?'err':''}">s${c.step} ${esc(c.name)} attempt ${c.args.attempt} ${esc(JSON.stringify(Object.fromEntries(Object.entries(c.args).filter(([k])=>!['app','attempt'].includes(k)))))}${c.error?' → '+esc(c.error):''}</div>`).join('')}</div>`:''}
      </div></details>`; };
  const seq = []; const seen = new Set();
  gates.forEach(g=>{seq.push({t:'gate',s:g}); seen.add(g.name);});
  skipped.forEach(k=>seq.push({t:'skip',s:k}));
  seq.sort((a,b)=>a.s.step-b.s.step);
  const pending = order.filter(n=>!seen.has(n)&&!skipped.some(k=>k.name===n));
  $('#timeline').innerHTML = (seq.map(e=>e.t==='gate'?gateHtml(e.s):`<div class="skipped" id="s${e.s.step}">s${e.s.step} skipped <b>${esc(e.s.name)}</b> — ${esc(e.s.note||'')}</div>`).join('')
    + (pending.length && !status ? pending.map(n=>`<div class="skipped">queued ${esc(n)}</div>`).join('') : '')) || '<div class="empty">no gate steps yet</div>';

  $('#findings').innerHTML = findings.length ? `<div class="findings">${findings.map(f=>`<div class="finding"><span class="n"><a href="#s${f.step}">s${f.step}</a></span>${pill(f.failure_class)}<b>${esc(f.name)}</b><span class="muted">${esc(f.note||'')}${f.args&&f.args.model_said!==undefined?' · model said '+esc(f.args.model_said)+', policy said '+esc(f.args.policy_said):''}</span></div>`).join('')}</div>` : '<div class="empty">no findings</div>';

  const sum = kind('summary').slice(-1)[0]; const claims = findings.filter(f=>f.name.startsWith('unsupported_claim:'));
  const link = t => esc(t).replace(/\[s(\d+)\]/g, (m,n)=>`<a href="#s${n}">[s${n}]</a>`);
  $('#summary').innerHTML = sum ? `<div class="summary">${pill(sum.name)} ${sum.result.ts?'<span class="muted mono">ts '+esc(sum.result.ts)+'</span>':''}
    ${sum.result.sentences.map(s=>`<p>${link(s)}</p>`).join('')}
    ${sum.result.dropped.map((s,i)=>{const c=claims.find(x=>x.args.sentence===s); return `<p class="dropped">${link(s)}<small>${pill('F8')} ${esc(c?c.args.reason:'unsupported')}</small></p>`;}).join('')}</div>` : '<div class="empty">no summary yet</div>';

  const undos = writes.filter(g=>g.result&&g.result.status==='applied'&&g.undo);
  $('#undo').innerHTML = undos.length ? `<ul class="undo">${undos.slice().reverse().map(g=>`<li class="${g.undo.supported===false?'no':''}"><a href="#s${g.step}">s${g.step}</a> ${esc(g.undo.op)} ${esc(JSON.stringify(g.undo.args))}${g.undo.supported===false?' — not supported: '+esc(g.undo.note||''):''}</li>`).join('')}</ul>` : '<div class="empty">nothing applied, nothing to undo</div>';
}

async function poll(){
  try { const r = await fetch('/trace.jsonl?ts='+Date.now(), {cache:'no-store'}); const text = await r.text(); const steps = parseJsonl(text);
    if (text !== window.__last) { window.__last = text; render(steps); }
    $('#live').innerHTML = `<b class="on">● live</b> ${steps.length} steps · polling ${esc(r.headers.get('x-trace-path')||'')}`;
  } catch(e) { $('#live').innerHTML = `<b>○ waiting for server</b>`; }
  setTimeout(poll, 500);
}
if (window.__TRACE__) { render(parseJsonl(window.__TRACE__)); } else { poll(); }
"""

BODY = """
<div class="wrap">
  <div class="head" id="head"></div>
  <div class="live" id="live"></div>
  <div class="counts" id="counts"></div>
  <h2>Pipeline</h2><div class="phases" id="phases"></div>
  <h2>Identity</h2><div id="identity"></div>
  <h2>Inventory and dispositions</h2><div class="filters" id="filters"></div><div id="inventory"></div>
  <h2>Execution timeline</h2><div id="timeline"></div>
  <h2>Findings</h2><div id="findings"></div>
  <h2>Summary posted</h2><div id="summary"></div>
  <h2>Undo records</h2><div id="undo"></div>
  <p class="muted" style="margin-top:40px">Every element on this page is a query over the trace file. Nothing is written from here. {links}</p>
</div>
"""


def page(trace_text: Optional[str], title: str, links: str = "") -> str:
    embedded = ""
    if trace_text is not None:
        embedded = "<script>window.__TRACE__ = " + json.dumps(trace_text) + ";</script>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title}</title><style>{CSS}</style></head><body>"
        + BODY.replace("{links}", links)
        + embedded
        + f"<script>{JS}</script></body></html>"
    )


def export(trace_path: str, out: str, scorecard: Optional[str] = None) -> str:
    with open(trace_path, encoding="utf-8") as fh:
        text = fh.read()
    links = f'<a href="{scorecard}">Scorecard</a>' if scorecard else ""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page(text, f"Offboard run · {os.path.basename(trace_path)}", links))
    return out


def serve(trace_path: str, port: int, scorecard: Optional[str] = None) -> None:
    links = f'<a href="{scorecard}">Scorecard</a>' if scorecard else ""
    html = page(None, "Offboard run console", links).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/trace.jsonl"):
                body = b""
                if os.path.exists(trace_path):
                    with open(trace_path, "rb") as fh:
                        body = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Trace-Path", trace_path)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stdout.write(f"console: http://127.0.0.1:{port}/  watching {trace_path}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m report.console", description="Render one offboarding trace as a static page, or serve it live.")
    p.add_argument("--trace", default="traces/run.jsonl")
    p.add_argument("--out", default="console.html")
    p.add_argument("--serve", type=int, metavar="PORT", help="serve the page and poll the trace file instead of exporting")
    p.add_argument("--scorecard", help="relative link to scorecard.html shown in the footer")
    args = p.parse_args(argv)
    if args.serve:
        serve(args.trace, args.serve, args.scorecard)
        return 0
    out = export(args.trace, args.out, args.scorecard)
    sys.stdout.write(f"console: {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
