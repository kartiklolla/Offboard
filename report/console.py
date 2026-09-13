from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from report.theme import CSS as THEME_CSS, FONTS

CSS = THEME_CSS + """
.console .head { display:flex; flex-wrap:wrap; align-items:baseline; gap:12px 20px; margin-top:16px }
.console .head h1 { font-size:40px }
.console .live { font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--smoke); margin-top:10px; display:flex; align-items:center; gap:8px }
.counts { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; margin-top:28px }
.count { border:1px solid var(--ash); border-radius:24px; padding:16px 18px 14px; background:var(--parchment) }
.count b { display:block; font-family:var(--serif); font-weight:400; font-size:32px; line-height:1.1; font-variant-numeric:tabular-nums }
.count span { font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--smoke) }
.console h2 { font-size:28px; margin:64px 0 20px; padding-top:24px; border-top:1px solid var(--ash) }
.phases { display:grid; grid-template-columns:repeat(6,1fr); gap:8px }
.phase { border:1px solid var(--ash); border-radius:9999px; padding:10px 18px; font-size:12px; display:flex; flex-direction:column; gap:2px; background:var(--parchment) }
.phase.done { background:var(--mint); border-color:transparent } .phase.open { background:var(--periwinkle); border-color:transparent; animation:pulse 1.4s infinite }
.phase b { font-weight:500; text-transform:uppercase; letter-spacing:-.033em } .phase span { color:var(--graphite); font-size:11.5px }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px }
.card h3 { font-family:var(--mono); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:-.033em; display:flex; justify-content:space-between; align-items:center; margin-bottom:10px }
.card .row { display:flex; justify-content:space-between; gap:12px; font-size:13px; padding:6px 0; border-bottom:1px solid var(--ash-soft) } .card .row:last-child { border-bottom:none }
tr.trap td:first-child { box-shadow:inset 3px 0 0 var(--offblack) }
#inventory td:nth-child(2), #inventory td:nth-child(3), #inventory td:nth-child(4) { white-space:nowrap }
#inventory td:first-child { overflow-wrap:anywhere; min-width:150px }
.filters { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap }
.filters button { border:1px solid var(--ash); background:var(--parchment); color:var(--graphite); padding:6px 14px; border-radius:9999px; font:inherit; font-size:12px; text-transform:uppercase; letter-spacing:-.033em; cursor:pointer }
.filters button.on { background:var(--offblack); color:var(--parchment); border-color:var(--offblack) }
.gate { border:1px solid var(--ash); border-radius:24px; background:var(--paper); margin:8px 0 }
.gate.failed_apply, .gate.failed_postcondition { border-color:var(--coral) } .gate.needs_approval, .gate.blocked_precondition { border-color:var(--gold) }
.gate summary { list-style:none; cursor:pointer; padding:12px 18px; display:flex; gap:12px; align-items:center; flex-wrap:wrap }
.gate summary::-webkit-details-marker { display:none }
.gate summary .n { color:var(--smoke); font-size:12px; min-width:44px }
.gate summary .name { font-weight:500 }
.gate summary .diff { color:var(--graphite); flex:1 1 200px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12.5px }
.gate .body { padding:12px 18px 16px 74px; display:grid; grid-template-columns:140px 1fr; gap:6px 12px; font-size:12.5px; border-top:1px solid var(--ash-soft) }
.gate .body .k { color:var(--smoke); text-transform:uppercase; letter-spacing:-.033em; font-size:11px; padding-top:2px }
.gate .calls { grid-column:1 / -1; margin-top:8px; border-top:1px solid var(--ash-soft); padding-top:8px }
.gate .calls div { font-size:12px; color:var(--graphite) } .gate .calls .err { color:var(--crimson) }
.skipped { padding:8px 18px; color:var(--smoke); font-size:12.5px; border:1px dashed var(--ash); border-radius:9999px; margin:6px 0 }
.findings { display:flex; flex-direction:column; gap:8px }
.finding { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; border:1px solid var(--ash); border-radius:24px; padding:10px 18px; font-size:13px; background:var(--parchment) }
.finding .n { color:var(--smoke); font-size:12px }
.summary p { margin:8px 0; padding:14px 20px; border:1px solid var(--ash); border-radius:24px; background:var(--paper); font-family:var(--serif); font-size:18px; line-height:1.35 }
.summary p.dropped { text-decoration:line-through; color:var(--smoke) } .summary p.dropped small { text-decoration:none; display:block; font-family:var(--mono); font-size:12px; color:var(--crimson); margin-top:6px }
.summary a { color:var(--lake) }
.undo { list-style:none; padding:0; margin:0 } .undo li { font-size:12.5px; padding:8px 0; border-bottom:1px solid var(--ash-soft) } .undo li a { color:var(--lake) } .undo .no { color:var(--crimson) }
.empty { color:var(--smoke); font-style:italic; padding:8px 0 }
.foot { margin-top:64px; color:var(--smoke); font-size:12px; border-top:1px solid var(--ash); padding-top:16px }
:target { outline:2px solid var(--lake); outline-offset:3px; border-radius:24px }
@media (max-width:820px) { .phases { grid-template-columns:repeat(2,1fr) } .gate .body { grid-template-columns:1fr; padding-left:18px } }
"""

JS = r"""
const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pill = (t, cls) => `<span class="tag ${esc(cls||t)}">${esc(t)}</span>`;
const TRAP_RULES = ['R2','R3','R5','R9'];
const isTrap = (r, ov, ij) => Boolean(ij) || Boolean(ov) || TRAP_RULES.includes(r.rule);
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
  ].map(([b,l])=>`<div class="count glow"><b>${esc(b)}</b><span>${esc(l)}</span></div>`).join('');

  const phaseNames = ['resolve_identity','inventory','classify','plan','execute','report'];
  const phases = kind('phase'); const open = steps.length && !status ? phaseNames.filter(p=>!phases.some(x=>x.name===p))[0] : null;
  $('#phases').innerHTML = phaseNames.map(p => { const ph = phases.find(x=>x.name===p); const children = steps.filter(s=>s.parent===(ph||{}).step).length;
    return `<div class="phase glow ${ph?'done':(p===open?'open':'')}"><b>${esc(p.replace('_',' '))}</b><span>${ph?children+' steps · '+ph.latency_ms+' ms':(p===open?'running…':'')}</span></div>`; }).join('');

  const ids = kind('identity'); const idOv = findings.filter(f=>f.name.startsWith('override:identity:'));
  $('#identity').innerHTML = ids.length ? `<div class="cards">${ids.map(i => { const r=i.result; const ov = idOv.find(f=>f.name.endsWith(':'+i.name));
    return `<div class="card glow" id="s${i.step}"><h3><span><span class="dot ${esc(i.name)}"></span>${esc(i.name)}</span> ${pill(r.status)}</h3>
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
    return `<tr class="${isTrap(r, ov, ij)?'trap':''}" id="s${d.step}"><td class="mono">${esc(res)}</td><td><span class="dot ${esc(app)}"></span>${esc(app)}</td><td>${esc(kind_)}</td>
      <td>${pill(r.disposition)}${r.transfer_to?` <span class="muted">→ ${esc(r.transfer_to)}</span>`:''}</td>
      <td>${r.rule?pill(r.rule,'rule'):''} <span class="muted">${esc(r.source)}</span>${ov?` ${pill(ov.failure_class)} <span class="muted">model said ${esc(ov.args.model_said ?? 'nothing')}</span>`:''}</td>
      <td>${ij?pill('injection','F7')+' <span class="muted">'+esc(ij.args.field)+'</span>':''}</td><td class="muted">${esc(r.reason)}</td></tr>`; }).join('');
  $('#inventory').innerHTML = disps.length ? `<div class="tablewrap"><table><thead><tr><th>resource</th><th>app</th><th>kind</th><th>disposition</th><th>rule · source</th><th>content</th><th>reason</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">no dispositions yet</div>';

  const plan = kind('plan').find(p=>p.name==='actions'); const order = plan ? plan.result.order : gates.map(g=>g.name);
  const skipped = kind('skipped');
  const stage = (k,v) => v===undefined||v===null ? '' : `<div class="k">${k}</div><div>${v}</div>`;
  const gateHtml = g => { const s = g.result?g.result.status:'running'; const calls = steps.filter(c=>c.parent===g.step&&c.kind==='tool_call');
    const undo = g.undo||{};
    return `<details class="gate glow ${esc(s)}" id="s${g.step}" ${/^failed|needs_approval/.test(s)?'open':''}><summary><span class="n">s${g.step}</span><span class="name">${esc(g.name)}</span>${pill(s)}${pill(g.risk)}<span class="diff">${esc(g.dry_run||'')}</span></summary>
      <div class="body">
        ${stage('1 precondition', g.precondition?`${g.precondition.ok?'ok':'false'} <span class="muted mono">${esc(JSON.stringify(g.precondition.value))}</span>`:undefined)}
        ${stage('2 diff', g.dry_run?`<span class="diff">${esc(g.dry_run)}</span>`:undefined)}
        ${stage('3 approval', g.approval?`${g.approval.granted?'granted':'not granted'} <span class="muted mono">${esc(g.approval.key)}${g.approval.strict?' · strict':''}</span>`:undefined)}
        ${stage('4 apply', g.result?(g.error?`<span class="err mono">${esc(g.error)}</span>`:(['applied','failed_postcondition'].includes(s)?'called':'not called')):undefined)}
        ${stage('5 read-back', g.postcondition?`${g.postcondition.ok?'confirmed':'<b>not confirmed</b>'} <span class="muted">after ${g.postcondition.attempts} read${g.postcondition.attempts>1?'s':''}</span>${g.failure_class?' '+pill(g.failure_class):''}`:undefined)}
        ${stage('undo', undo.op?`<span class="mono">${esc(undo.op)} ${esc(JSON.stringify(undo.args))}</span> ${undo.supported===false?'<span class="tag needs_human">not supported</span> <span class="muted">'+esc(undo.note||'')+'</span>':''}`:undefined)}
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

  $('#findings').innerHTML = findings.length ? `<div class="findings">${findings.map(f=>`<div class="finding glow"><span class="n"><a href="#s${f.step}">s${f.step}</a></span>${pill(f.failure_class)}<b>${esc(f.name)}</b><span class="muted">${esc(f.note||'')}${f.args&&f.args.model_said!==undefined?' · model said '+esc(f.args.model_said ?? 'nothing')+', policy said '+esc(f.args.policy_said ?? 'nothing'):''}</span></div>`).join('')}</div>` : '<div class="empty">no findings</div>';

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
    $('#live').innerHTML = `<span class="pulse"></span> live · ${steps.length} steps · ${esc(r.headers.get('x-trace-path')||'')}`;
  } catch(e) { $('#live').innerHTML = `waiting for server`; }
  setTimeout(poll, 500);
}
if (window.__TRACE__) { render(parseJsonl(window.__TRACE__)); } else { poll(); }
"""

BODY = """
<div class="wrap console">
  <nav class="nav">
    <a class="brand" href="/"><i></i>Offboard</a>
    <div class="links"><a href="/#how">How it works</a><a href="/#traps">Traps</a><a href="/#run">Run</a></div>
    <div class="actions">{links}<a class="btn small" href="/">Start over</a></div>
  </nav>
  <p class="eyebrow"><span class="dot"></span>Run console — one trace, read live</p>
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
  <p class="foot">Every element on this page is a query over the trace file. Nothing is written from here.</p>
</div>
"""


def page(trace_text: Optional[str], title: str, links: str = "") -> str:
    embedded = ""
    if trace_text is not None:
        embedded = "<script>window.__TRACE__ = " + json.dumps(trace_text) + ";</script>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        + FONTS
        + f"<title>{title}</title><style>{CSS}</style></head><body>"
        + BODY.replace("{links}", links)
        + embedded
        + f"<script>{JS}</script></body></html>"
    )


def export(trace_path: str, out: str, scorecard: Optional[str] = None) -> str:
    with open(trace_path, encoding="utf-8") as fh:
        text = fh.read()
    links = f'<a class="btn small black" href="{scorecard}">Scorecard</a>' if scorecard else ""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page(text, f"Offboard · {os.path.basename(trace_path)}", links))
    return out


def serve(trace_path: str, port: int, scorecard: Optional[str] = None) -> None:
    links = f'<a class="btn small black" href="{scorecard}">Scorecard</a>' if scorecard else ""
    html = page(None, "Offboard · run console", links).encode("utf-8")

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
