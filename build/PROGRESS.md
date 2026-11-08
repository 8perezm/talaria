# Mini Hermes Build — Progress Tracker

| Phase | Scope | Code+tests | Device verify | Notes |
|---|---|---|---|---|
| 0 | `/api/doctor` + state backup | DONE (89 passed) | DONE (healthy, heap 8.1M) | backup: `esp32_backup_20261107/` |
| 1 | Prompt tiers + provider fallback | DONE (114 passed) | — | UI fields deferred → Phase 9; stream prompt + tools preview still legacy (deferred, frozen-per-turn unaffected) |
| 2 | Memory v2 (two stores) | DONE (138 passed) | — | no per-entry 500-cap (store caps subsume); batch may empty store; no typography folding; clear_memory still device-store only |
| 3 | Skills mini | DONE (154 passed) | — | skill_view handles `bundle:` prefix (no extra slot); pending = one JSON/record; /update blocks bundles.json (skills/*.md unreachable by construction) |
| 4 | Sessions (search/new/journey) | CODE DONE (174) / DEVICE BLOCKED | `skills.py` vs `skills/` module collision → 500 on /api/skills. Fix: rename engine module, redeploy. App otherwise healthy (chat 3.3s, SSE clean, doctor SPIRAM_OCT) |
| 4b | Skills collision fix + redeploy | DONE (175 passed) | DONE (`skillstore.py` rename; /api/skills 200 empty, pending 200, chat+skills_list 200 zero-skills, doctor+status 200) |
| 5 | Cron mini | DONE (194 passed) | — | tick runs only with run_fn; run_now works paused; prompt>1500 refused; telegram stored, delivery deferred; webhook single-attempt best-effort |
| 6 | Delegation + exec_py | DONE (214 passed) | — | TOOL dicts live in root modules (no collision risk); tools_allow = intersect minus restart_device (hard-excluded); addToolsArray honors restriction; interrupted reserved |
| 7 | File tools + checkpoints | DONE (234 passed) | DONE checkpoint B (22 tools live, mask 4063231, todo/delegate/read_file verified, cron tick silent) | fsutil canonical + server delegates |
| 8 | Gateway (Telegram) | DONE (263 passed) | — | chat-stream unguarded (documented); tg_loop single-pass + main cadence; live test needs user bot token |
| 9 | Polish + parity UI | DONE (284 passed) | DONE final deploy (all pages/APIs 200, chat 4.1s, SSE clean, tg dormant) | browser GO pre-deploy; /api/rollback slow (~17s, pre-existing) |

## Exit criteria (PLAN §10) — verdict
- [x] `/api/doctor` green (SPIRAM_OCT, heap ~8M) · [x] two-store memory w/ usage + overflow guidance (host) · [x] search recalls pre-/new facts (host) · [x] delegated task ≤2 upstream calls (device: 42) · [x] file edit + rollback (host; rollback slow ~17s noted) · [x] suite green (284) · [x] parity matrix P1/P2 green
- [~] fallback answers with primary broken: HOST-tested only; device has no fallback configured
- [~] ≥3 agent-created skills through approval: HOST-tested only; device skills/ empty
- [~] cron delivers twice across reset: HOST-tested only; device cron empty (no stray jobs policy)
- [ ] Telegram round-trip: PENDING USER — BotFather token → tg.json → pair → verify (steps in Phase 8 report)
| 8 | Gateway (Telegram) | — | — | touches main.py |
| 7 | File tools + checkpoints | — | — | deploy checkpoint B after this |
| 8 | Gateway (Telegram) | — | — | touches main.py |
| 9 | Polish + parity UI | — | — | local browser test before device; final full deploy |

Deviations from PLAN.md: Phase 1 `/agent` HTML fields deferred to Phase 9 (backend/API only) to keep the turn small and UI work in one testable batch.
