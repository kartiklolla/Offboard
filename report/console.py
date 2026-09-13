from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

CSS = """
:root { --bg:#0C0F14; --panel:#12161D; --soft:#1A2029; --line:#252D39; --line-hi:#36404F; --ink:#E7EBF2; --muted:#8B97A8; --dim:#5C6878;
  --accent:#F5B84A; --accent-bg:#2A2110; --pass:#3DDC97; --pass-bg:#0F2A20; --fail:#FF6B6B; --fail-bg:#33171A; --warn:#F5B84A; --warn-bg:#2A2110; --info:#7AA2F7; --info-bg:#161F35; }
* { box-sizing:border-box }
html { background:var(--bg) }
body { margin:0; background:var(--bg); color:var(--ink); font:13.5px/1.55 "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background-image:linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px); background-size:48px 48px; background-position:-1px -1px; }
body::before { content:""; position:fixed; inset:0; background:radial-gradient(ellipse at 50% -10%, rgba(245,184,74,.10), transparent 55%); pointer-events:none }
.wrap { position:relative; max-width:1240px; margin:0 auto; padding:28px 24px 90px; }
.px { font-family:"Press Start 2P", "JetBrains Mono", monospace; text-transform:uppercase; letter-spacing:.04em }
.brand { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 18px; border:1px solid var(--line-hi); background:linear-gradient(180deg, rgba(255,255,255,.02), transparent), var(--panel); margin-bottom:22px }
.brand .word { font-size:22px; color:var(--accent); text-shadow:0 0 14px rgba(245,184,74,.55), 0 0 2px rgba(245,184,74,.9); line-height:1 }
.brand .word small { display:block; font:11px/1.5 "JetBrains Mono", monospace; color:var(--muted); text-transform:none; letter-spacing:0; text-shadow:none; margin-top:8px }
.brand .tag { font-size:9px; color:var(--muted); text-align:right; line-height:1.9 }
.brand .tag b { display:block; color:var(--ink); font-size:10px }
h1 { font-size:20px; margin:0; font-weight:600; letter-spacing:-.01em }
h2 { font-family:"Press Start 2P", monospace; font-size:10px; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); margin:38px 0 12px; font-weight:400; display:flex; align-items:center; gap:12px }
h2::after { content:""; flex:1; height:1px; background:linear-gradient(90deg, var(--line-hi), transparent) }
.mono, code, .diff { font-family:inherit; font-size:12.5px }
.muted { color:var(--muted) }
.head { display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px; }
.head .muted { font-size:12px }
.pill { display:inline-block; padding:3px 9px; font-size:11px; font-weight:600; border:1px solid var(--line-hi); background:var(--soft); vertical-align:middle; text-transform:uppercase; letter-spacing:.06em }
.pill.clean, .pill.applied, .pill.resolved, .pill.posted { background:var(--pass-bg); color:var(--pass); border-color:rgba(61,220,151,.35) }
.pill.dirty, .pill.failed_apply, .pill.failed_postcondition { background:var(--fail-bg); color:var(--fail); border-color:rgba(255,107,107,.4) }
.pill.needs_human, .pill.needs_approval, .pill.blocked_precondition, .pill.escalate, .pill.suppressed { background:var(--warn-bg); color:var(--warn); border-color:rgba(245,184,74,.4) }
.pill.dry_run, .pill.skipped_dry_run, .pill.running, .pill.transfer_then_revoke { background:var(--info-bg); color:var(--info); border-color:rgba(122,162,247,.4) }
.pill.revoke { background:var(--soft); color:var(--ink) }
.pill.F1,.pill.F2,.pill.F3,.pill.F4,.pill.F5,.pill.F6,.pill.F7,.pill.F8 { background:var(--fail-bg); color:var(--fail); border-color:rgba(255,107,107,.4); font-family:"Press Start 2P", monospace; font-size:8px; padding:5px 7px }
.pill.rule { color:var(--muted); font-weight:500; text-transform:none; letter-spacing:0 }
.pill.irreversible { color:var(--fail); border-color:rgba(255,107,107,.3); background:transparent }
.pill.reversible { color:var(--muted); background:transparent }
.counts { display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr)); gap:8px; margin-top:16px }
.count { background:var(--panel); border:1px solid var(--line); padding:12px 12px 10px; position:relative }
.count::before { content:""; position:absolute; top:0; left:0; width:14px; height:2px; background:var(--accent) }
.count b { display:block; font-size:24px; font-variant-numeric:tabular-nums; line-height:1.1; font-weight:600 }
.count span { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em }
.phases { display:grid; grid-template-columns:repeat(6,1fr); gap:6px }
.phase { background:var(--panel); border:1px solid var(--line); padding:10px 12px; font-size:12px; position:relative }
.phase::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--line-hi) }
.phase.done::before { background:var(--pass) } .phase.open::before { background:var(--accent); animation:pulse 1.1s infinite }
.phase b { display:block; font-weight:600; text-transform:uppercase; letter-spacing:.06em; font-size:11px } .phase span { color:var(--muted); font-size:11.5px }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.35 } }
@media (prefers-reduced-motion: reduce) { .phase.open::before, .live b.on { animation:none } }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:8px }
.card { background:var(--panel); border:1px solid var(--line); padding:12px 14px }
.card h3 { margin:0 0 8px; font-size:12px; display:flex; justify-content:space-between; align-items:center; text-transform:uppercase; letter-spacing:.08em }
.card .row { display:flex; justify-content:space-between; gap:8px; font-size:12.5px; padding:3px 0; border-bottom:1px dashed var(--line) } .card .row:last-child { border-bottom:none }
.tablewrap { overflow-x:auto; border:1px solid var(--line); background:var(--panel) }
table { border-collapse:collapse; width:100%; font-size:12.5px }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top }
th { font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); background:var(--soft); font-weight:600 }
tr:last-child td { border-bottom:none }
tr.trap td:first-child { box-shadow:inset 3px 0 0 var(--accent) }
.filters { display:flex; gap:6px; margin-bottom:10px; flex-wrap:wrap }
.filters button { border:1px solid var(--line-hi); background:var(--panel); color:var(--muted); padding:4px 12px; font:inherit; font-size:11px; text-transform:uppercase; letter-spacing:.08em; cursor:pointer }
.filters button.on { background:var(--accent); color:#1A1206; border-color:var(--accent); font-weight:700 }
.filters button:focus-visible { outline:2px solid var(--accent); outline-offset:2px }
.gate { border:1px solid var(--line); background:var(--panel); margin:6px 0; position:relative }
.gate::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--line-hi) }
.gate.applied::before { background:var(--pass) } .gate.failed_apply::before, .gate.failed_postcondition::before { background:var(--fail) }
.gate.needs_approval::before, .gate.blocked_precondition::before { background:var(--warn) } .gate.skipped_dry_run::before { background:var(--info) }
.gate summary { list-style:none; cursor:pointer; padding:9px 14px; display:flex; gap:12px; align-items:center; flex-wrap:wrap }
.gate summary::-webkit-details-marker { display:none }
.gate summary .n { color:var(--dim); font-size:11px; min-width:44px }
.gate summary .name { font-weight:600 }
.gate summary .diff { color:var(--muted); flex:1; min-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.gate .body { padding:2px 14px 12px 70px; display:grid; grid-template-columns:130px 1fr; gap:4px 12px; font-size:12px; border-top:1px dashed var(--line); margin-top:2px; padding-top:10px }
.gate .body .k { color:var(--accent); text-transform:uppercase; letter-spacing:.06em; font-size:10px; padding-top:2px }
.gate .calls { grid-column:1 / -1; margin-top:8px; border-top:1px dashed var(--line); padding-top:8px }
.gate .calls div { font-size:11.5px; color:var(--muted) }
.gate .calls .err { color:var(--fail) }
.skipped { padding:6px 14px 6px 17px; color:var(--muted); font-size:12px; border-left:3px solid var(--line-hi); margin:4px 0; background:var(--panel) }
.findings { display:flex; flex-direction:column; gap:6px }
.finding { display:flex; gap:12px; align-items:baseline; background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--fail); padding:8px 12px; font-size:12.5px }
.finding .n { color:var(--dim); font-size:11px } .finding .n a { color:var(--dim) }
.summary p { margin:6px 0; padding:9px 14px; background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--pass) }
.summary p.dropped { text-decoration:line-through; color:var(--muted); border-left-color:var(--fail) } .summary p.dropped small { text-decoration:none; display:block; color:var(--fail); margin-top:4px }
.summary a, a { color:var(--accent); text-decoration:none }
.undo li { font-size:12px; margin:4px 0 } .undo .no { color:var(--warn) }
.empty { color:var(--dim); font-style:italic; padding:8px 0 }
.live { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; margin-top:8px } .live b.on { color:var(--pass); animation:pulse 1.6s infinite }
.foot { margin-top:48px; color:var(--dim); font-size:11.5px; border-top:1px solid var(--line); padding-top:14px }
:target { outline:2px solid var(--accent); outline-offset:2px }
@media (max-width:800px) { .phases { grid-template-columns:repeat(3,1fr) } .gate .body { grid-template-columns:1fr; padding-left:14px } .brand { flex-direction:column; align-items:flex-start } .brand .tag { text-align:left } }
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
      <td>${r.rule?pill(r.rule,'rule'):''} <span class="muted">${esc(r.source)}</span>${ov?` ${pill(ov.failure_class)} <span class="muted">model said ${esc(ov.args.model_said ?? 'nothing')}</span>`:''}</td>
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

  $('#findings').innerHTML = findings.length ? `<div class="findings">${findings.map(f=>`<div class="finding"><span class="n"><a href="#s${f.step}">s${f.step}</a></span>${pill(f.failure_class)}<b>${esc(f.name)}</b><span class="muted">${esc(f.note||'')}${f.args&&f.args.model_said!==undefined?' · model said '+esc(f.args.model_said ?? 'nothing')+', policy said '+esc(f.args.policy_said ?? 'nothing'):''}</span></div>`).join('')}</div>` : '<div class="empty">no findings</div>';

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
  <div class="brand">
    <div class="word px">Offboard<small>revoke · prove · undo — one trace, read live</small></div>
    <div class="tag px"><b>run console</b>GitHub · Slack · Drive · Sheets<br>every write through the gate</div>
  </div>
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
  <p class="foot">Every element on this page is a query over the trace file. Nothing is written from here. {links}</p>
</div>
"""


def page(trace_text: Optional[str], title: str, links: str = "") -> str:
    embedded = ""
    if trace_text is not None:
        embedded = "<script>window.__TRACE__ = " + json.dumps(trace_text) + ";</script>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Press+Start+2P&family=JetBrains+Mono:wght@400;500;600;700&display=swap'>"
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
        fh.write(page(text, f"Offboard · {os.path.basename(trace_path)}", links))
    return out


def serve(trace_path: str, port: int, scorecard: Optional[str] = None) -> None:
    links = f'<a href="{scorecard}">Scorecard</a>' if scorecard else ""
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
