from __future__ import annotations

FONTS = (
    "<link rel='preconnect' href='https://fonts.googleapis.com'>"
    "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;500&display=swap'>"
)

CSS = """
:root { --parchment:#f6f3f1; --paper:#fbf9f8; --lake:#2b59d1; --periwinkle:#cfdaf5; --sky:#a0b5eb; --mint:#a7fccd; --coral:#ff9473; --gold:#ecda98; --crimson:#f37a0a;
  --offblack:#242424; --ink:#000000; --graphite:#4e4d4d; --smoke:#797776; --ash:#cecac8; --ash-soft:#e6e2df;
  --serif:"Newsreader", "Untitled Serif", ui-serif, Georgia, "Times New Roman", serif; --mono:"JetBrains Mono", "ABC Diatype Mono", ui-monospace, SFMono-Regular, Menlo, monospace; }
* { box-sizing:border-box }
html { background:var(--parchment) }
body { margin:0; background:var(--parchment); color:var(--offblack); font:14px/1.35 var(--mono); letter-spacing:-.02em; -webkit-font-smoothing:antialiased }
a { color:inherit; text-decoration:none }
a:focus-visible, button:focus-visible { outline:2px solid var(--lake); outline-offset:3px }
.wrap { max-width:1240px; margin:0 auto; padding:0 32px 96px }
h1, h2, h3, .serif { font-family:var(--serif); font-weight:400; letter-spacing:-.02em; line-height:1.2; margin:0; text-wrap:balance }
h1 { font-size:48px } h2 { font-size:32px } h3 { font-size:24px }
.eyebrow { font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--smoke) }
.graphite { color:var(--graphite) } .smoke { color:var(--smoke) }
.nav { display:flex; align-items:center; justify-content:space-between; gap:24px; height:80px }
.nav .brand { display:flex; align-items:center; gap:10px; font-family:var(--serif); font-size:26px; letter-spacing:-.02em }
.nav .brand i { width:12px; height:12px; border-radius:50%; background:var(--offblack); display:inline-block }
.nav .links { display:flex; gap:28px; font-size:14px; text-transform:uppercase; letter-spacing:-.022em }
.nav .links a:hover { color:var(--graphite) }
.nav .actions { display:flex; gap:10px }
.btn { display:inline-flex; align-items:center; gap:8px; padding:12px 24px; border-radius:100px; border:1px solid var(--offblack); background:transparent; color:var(--offblack); font:500 13px/1.2 var(--mono); text-transform:uppercase; letter-spacing:-.02em; cursor:pointer; white-space:nowrap }
.btn.black { background:var(--offblack); color:var(--parchment) }
.btn.blue { background:var(--lake); border-color:var(--lake); color:#fff }
.btn.small { padding:8px 16px; font-size:12px }
.btn[disabled] { opacity:.45; cursor:default }
.tag { display:inline-flex; align-items:center; gap:6px; padding:5px 12px; border-radius:9999px; border:1px solid var(--ash); background:var(--parchment); font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--offblack); white-space:nowrap }
.tag.applied, .tag.clean, .tag.resolved, .tag.posted { background:var(--mint); border-color:transparent }
.tag.failed_apply, .tag.failed_postcondition, .tag.dirty, .tag.F1, .tag.F2, .tag.F3, .tag.F4, .tag.F5, .tag.F6, .tag.F7, .tag.F8 { background:var(--coral); border-color:transparent }
.tag.needs_approval, .tag.needs_human, .tag.blocked_precondition, .tag.escalate, .tag.suppressed { background:var(--gold); border-color:transparent }
.tag.skipped_dry_run, .tag.dry_run, .tag.running, .tag.transfer_then_revoke { background:var(--periwinkle); border-color:transparent }
.tag.irreversible { border-color:var(--offblack) } .tag.reversible, .tag.rule { color:var(--graphite) }
.card { background:var(--parchment); border:1px solid var(--ash); border-radius:24px; padding:24px }
.card.lg { border-radius:40px; padding:40px }
.card.peri { background:var(--periwinkle); border-color:transparent }
.hair { border:0; border-top:1px solid var(--ash); margin:0 }
.tablewrap { overflow-x:auto; border:1px solid var(--ash); border-radius:24px; background:var(--paper) }
table { border-collapse:collapse; width:100%; font-size:13px }
th, td { text-align:left; padding:12px 16px; border-bottom:1px solid var(--ash-soft); vertical-align:top }
th { font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--smoke); font-weight:500 }
tr:last-child td { border-bottom:none }
.stat { border:1px solid var(--ash); border-radius:24px; padding:20px 24px; background:var(--parchment) }
.stat b { display:block; font-family:var(--serif); font-weight:400; font-size:40px; line-height:1.1; letter-spacing:-.02em }
.stat span { font-size:12px; text-transform:uppercase; letter-spacing:-.033em; color:var(--smoke) }
.pulse { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--lake); animation:pulse 1.4s infinite }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.3 } }
@media (prefers-reduced-motion: reduce) { .pulse, .flow-dot { animation:none } }
.wash { position:absolute; inset:auto; filter:blur(70px); opacity:.8; border-radius:50%; pointer-events:none }
@media (max-width:820px) { .wrap { padding:0 20px 64px } h1 { font-size:36px } h2 { font-size:28px } .nav .links { display:none } }
"""
