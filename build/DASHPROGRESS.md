# Dashboard Build — Progress Tracker (see build/DASHBOARD-PLAN.md)

Reference screenshots: `C:\Users\miguel\AppData\Local\Temp\opencode\dashref\` (config/sessions/channels/system).

| Phase | Scope | Code+tests | Browser (local) | Device |
|---|---|---|---|---|
| D0 | Shell (dash.css/icons.svg/nav) + `/admin` proof page | DONE (295) | DONE browser-GO | DONE device (13.7MB free, +19.5KB) | follow-up queued: doctor heap sample under GC pressure (gc.collect before mem_free) |
| D2 | `/sessions` + `/logs` pages | DONE (306) | DONE browser-GO after fix | DONE device (−24.6KB, 13.72MB free) | level-filter fix also fixed poll history loss |
| D3 | Stats counters + `/keys` page (+ doctor gc.collect fix) | DONE (323) | DONE browser-GO (no leaks) | DONE device (13.71MB free; heap 8.03M first poll) |
| D4 | `/cron` page + `edit` op + `/skills` page | DONE (342) | DONE browser-GO | DONE device (−32KB, edit exercised, zero residue) |
| D5 | `/channels` + `/system` pages (+ backup/prune/reboot APIs) | DONE (356) | DONE browser-GO (119/119) | DONE device (−48KB, backup redacted, gw dormant) |
| D6 | Retrofit old pages + docs/AGENTS deltas + full matrix | DONE (367) | DONE parent visual pass (admin/functions/system shot live, 0 console errors) | DONE device matrix (18/18 200, cron round-trip, zero residue) |
| D7 | One-theme-everywhere (dark-only, 10 pages recolored) | DONE (392) | — (device-deploy wave) | DONE device (10/10 200 + `/` 200, chat dark markers OK, `/api/chat` 200 real reply, SSE smoke deltas+DONE; www −8.7KB, statvfs 12.99MB free) | `server.py`+`dash.css` unchanged on device (sizes match, not deployed); `/chat` 404 pre-existing (`/` serves chat.html); statvfs check drops to REPL — recovered via soft-reset, app running |

Note: plan §7 labels D1..D10; execution merges into 6 subagent waves (D0=shell+admin, D2=sessions+logs, D3=stats+keys, D4=cron+skills, D5=channels+system, D6=final). Each wave: code → pytest → local browser GO → device deploy.

## D6 notes (final wave, 2026-11-07, suite 367 green, no device contact)

- Retrofitted `/functions /agent /stats` (+2424B each: 27371→29795, 27313→29737,
  19657→22081): `data-shell="1"` + dash.css link (BEFORE page `<style>`, so page
  rules win ties like `.bar`) + byte-identical canonical nav + highlight script.
  Topnav buttons KEPT (theme/console/hamburger wired by page JS). Shell page set
  for the device-matrix pass (11): admin, sessions, logs, keys, cron, skills,
  channels, system, functions, agent, stats.
- DEVIATION — `/` (chat.html, 38526B) NOT shelled, keeps topnav only: full-viewport
  streaming app (100dvh flex-column, overflow:hidden); a fixed 230px sidebar would
  overlap/warp it and fitting it needs page-CSS changes = behavior change. Scripts
  byte-untouched (streaming markers pinned in `tests/test_dash6.py`).
- Minor known tint: retrofitted pages keep their light/dark theme toggle while the
  shell is dark-first — in light theme, plain links render shell-cream
  (`a{color:var(--txt)}`, page has no light-theme link color; dark theme keeps its
  `#8ab4ff`). Dual nav on mobile (shell top-nav + page hamburger) accepted.
- `www/docs.html` (+2730B → 28741): content-only Dashboard section (page map,
  `/api/reboot` safe vs `/api/reset` FACTORY-WIPE warning, backup-restore via
  /files note). No shell. AGENTS.md gained a Dashboard-shell deltas section.
- Also dropped two stale all-"—" placeholder rows (old D5/D6 dups) from the table.
