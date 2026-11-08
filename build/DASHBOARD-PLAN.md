# Dashboard Plan — Mini Hermes Web GUI (Hermes web-dashboard parity)

**Shipped 2026-11-07** — full suite 367 green (`tests/test_dash*.py`, incl. 11 new
D6 tests). Deviations logged in `build/DASHPROGRESS.md` (D6 notes: `/` chat keeps
its topnav, no shell — deliberate; retrofitted pages keep topnav buttons too).

Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard
(fetched 2026-11-07; page is ~1550 lines — auth-provider reference tail not
fetched, irrelevant: no OAuth/OIDC on ESP32). Prior build state: `build/PROGRESS.md`
(all 9 phases + collision fix deployed, 284 tests, 22 tools).

## 1. What the Hermes dashboard is

Browser admin for a Hermes installation (`hermes dashboard` → FastAPI on
`127.0.0.1:9119`, React frontend, xterm.js PTY running the real TUI).
15 pages: **Status** (version, gateway, active/recent sessions, 5s refresh,
resource-pressure banners), **Chat** (full TUI in browser + session rail +
workspace picker), **Config** (schema-driven editor of all 150+ fields),
**API Keys** (`.env` manager, redacted previews, categorized), **Sessions**
(FTS5 search, role-colored Markdown, tool-call blocks, rename/export/prune/
delete, Chats/Automation filter), **Logs** (file/level/component filter, live
tail), **Analytics** (tokens, cache %, cost, daily + per-model tables),
**Cron** (CRUD + pause/resume/edit/trigger), **Profiles** (machine-level
switcher, `?profile=` deep links), **Skills** (toggle + toolsets + hub install
with live log), **MCP** (servers + approved catalog), **Webhooks**, **Pairing**
(approve/revoke codes), **Channels** (per-platform forms, enable/test,
gateway restart), **System** (host stats, Portal, curator, gateway lifecycle,
memory reset, credential pool, background ops incl. doctor/backup/rollback-
prune/hooks). Plus a consumed-by-frontend **REST API** and a loopback-open /
non-loopback-gated **auth model** (fail-closed without a provider).

## 2. What we already have (page → Hermes equivalent)

| Ours | Hermes equiv | State |
|---|---|---|
| `/` chat (SSE streaming, history restore, slash cmds) | Chat tab (mini; no PTY) | HAVE — keep as primary surface |
| `/agent` (endpoint/model/fallback/iters/approvals + cron card) | Config (partial) + Cron (partial) | HAVE, promote pieces |
| `/functions` (toolsets groups, pending queues, clear_user) | Skills/Toolsets (partial) + part of System/memory | HAVE, extend |
| `/files` (explorer + editor + modal) | — (no equiv; ours is unique) | HAVE, keep |
| `/stats` (telemetry) | Status (partial) + Analytics (partial) | HAVE, promote |
| `/journey` (learning timeline + export) | Learning graph (mini) | HAVE, keep |
| `/docs` (how-to) | docs site (mini inline) | HAVE, keep |
| `/setup`, `/wifi`, `/update` | onboarding + System/update | HAVE, keep |
| `/api/*` (45 routes — status/stats/doctor/auth/scan/wifi/agent/models/config/debug/chat/tools/memory/skills/journey/trajectory/cron/gateway/logs/files/rollback/reset/update) | REST API (partial) | HAVE, 6 small gaps (§5) |

## 3. Gap → plan verdict

| Hermes page | Mini verdict | Plan item |
|---|---|---|
| Status landing + pressure banner | BUILD | D1 `/admin`: vitals (heap + PSRAM verdict, uptime, IP), banner (heap<1M = wrong-build, state-file sizes), tg/cron/skills/memory-at-a-glance, recent turns, quick links. Chat stays `/`. |
| Sessions browser | BUILD | D2 `/sessions`: current + `.prev` turns, search (`/api/memory?q=`), export link, `/new` rotate button. No rename (single session). |
| Logs viewer | BUILD | D3 `/logs`: file/level/lines selectors + 5s auto-refresh toggle over existing `/api/logs`. |
| Analytics | PROMOTE | D4 `/stats`: add RAM-cheap counters (turns since boot, per-tool calls, last/upstream ms) to `/api/stats`; daily/cost out of scope (no token metering on device). |
| Config editor | HAVE (extend) | D5a: schema-ish grouping already on `/agent`; add `edit` affordance parity only (validation hints). No 150-field render. |
| API Keys | BUILD (small) | D5b `/keys`: endpoint/key (redacted preview, existing maskedKey), auth-token set, Telegram = file-only note + link to channels. Secrets never render full. |
| Cron full page | PROMOTE | D6 `/cron`: table (state/last/next) + pause/resume/**edit**/trigger/delete + create. Needs backend `edit` op (§5). |
| Skills page | BUILD | D7 `/skills`: index table + view modal + propose form + pending approve/reject + bundles list. APIs exist. |
| Channels + Pairing | BUILD | D8 `/channels`: Telegram status/test, pairing requests approve/revoke, allowlist, BotFather guide. Webhooks: SKIP (no platform). |
| System ops | BUILD | D9 `/system`: doctor card, state backup download (§5), rollback list/**prune** (§5), restart (existing `/api/reset` semantics — verify first), link to `/update`. |
| MCP / catalog, Profiles, Webhooks, PTY chat, OAuth/OIDC, cost analytics, skill-hub install | SKIP | §4 rationale; revisit only if hardware changes. |

## 4. Explicit non-goals (won't fit, don't retry)

- **PTY/TUI-in-browser** (needs POSIX PTY + Node bundle): our SSE chat page IS the mini equivalent.
- **Multi-profile + `?profile=` switcher**: single home; Telegram chats intentionally share stores (documented in PLAN).
- **OAuth/OIDC providers**: our auth model (open AP setup + token-gated STA, fail-soft 401s, `?token=` downloads) is the mini of loopback-open/gated-closed. No login page.
- **MCP servers + catalog, skill-hub installs, webhooks platform, per-model cost**: no RAM/process budget; `web_search` tool (PLAN slot 23) still unclaimed.
- **Skill enable/disable toggles**: tools_mask covers *tools*; skills are load-on-demand (index is already ≤1KB). A `disabled_skills[]` list is 20 lines — allowed iff free, lowest priority.

## 5. Backend gaps (all small; API-only, no slots)

1. `cron.handle`: add `edit{id, prompt?, every_s?, deliver?, skills?}` (reschedule from now; validation like `add`).
2. `checkpoint.py` + `POST /api/rollback`: add `prune{keep?}` (keep N newest, default 4; report freed).
3. NEW `GET /api/backup` (auth): one JSON `{config-redacted?, memory, user, chatlog, cron, skills, bundles}` — MUST redact `api_key/wifi_pass/auth_token/bot_token` (reuse maskedKey shapes, never raw). Download via `?token=`. No restore v1 (document; restore = /files editor + reboot).
4. `/api/stats`: add `turns_since_boot`, `tool_calls{}` (RAM dict, reset on boot — document), `last_chat_ms`, `last_upstream_ms` (measured in chat handlers; 4-line diff).
5. Verify `/api/reset` semantics before D9 wires a Restart button (reboot vs factory?): read code first; if factory-wipe, gate behind typed confirm + document, else simple modal.
6. `/update` blocklist + `_DOCTOR_FILES`: cover any new state (none expected — new pages use existing APIs).

## 6. Shell + budgets (applies to all Dx)

- Shared shell `www/dash.css` + identical nav snippet per page (see §10).
Zero `alert/confirm/prompt`, grep-gated in tests.
- Flash budget: current www ≈ 250KB; new pages (admin, sessions, logs, skills, cron, channels, system, keys ≈ 8 × ≤15KB) → total ≤ ~370KB. Verify LittleFS headroom on device during deploy (`os.statvfs`); if tight, D9 documents what to drop (keys→fold into agent, logs→keep API-only).

## 10. Visual spec — match their screenshots (verified from 4 reference PNGs in temp `dashref/`)

Reference: Config / Sessions / Channels / System pages (dark terminal aesthetic).

**Tokens** (`www/dash.css` `:root`; approximate — sampled by eye, no picker):
`--bg: #0b1411` (deep green-black) · `--panel: #101c17` · `--line: #2a3f35`
(thin olive borders everywhere) · `--txt: #d6d2c0` (cream) ·
`--dim: #8a947f` · `--faint: #5a6a5e` · `--grn: #35d07f` (live dots/ok) ·
`--red: #e5484d` (delete/errors) · `--amb: #e0a63c` (warnings/paused) ·
`--btn: #ece5d3` cream button bg with `--btntxt: #1a241f` ·
`--input: #0e1a15` input bg, border `--line2: #33473c`.
Font: mono everywhere — `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`, system fallback. **No webfonts, no CDN, no external links**: the device serves offline (AP mode has no internet); everything self-contained.

**Layout**: fixed left sidebar ~230px (logo `MINI-HERMES AGENT`, nav with icons,
`System` block: gateway status, active chats, Restart, Update; skin/version
footer) + main column (top bar: page title left, actions right; content cards).
**Mobile adaptation** (their UI is desktop-first; ours is phone-first):
below ~760px the sidebar becomes a horizontal scrollable top nav — this is a
deliberate deviation, phone users are our primary surface.

**Components** (one class each in dash.css, reused on every page):
stat cards (big number + dim label + optional filter chips), search input,
row cards (icon + title + dim subline left; badges + icon-buttons right),
badges (`live` green dot, platform/source outline tag, `disabled`/`paused`
amber tag), toggle switches, cream primary buttons (`CONFIGURE`/`SAVE` style),
outlined icon buttons (edit/download/delete/refresh), notice banners,
section cards (icon + letterspaced title), form rows (CAPS label + dim
description + full-width input), definition grids (System page host block).

**Icons**: single `www/icons.svg` sprite referenced via `<use>` (one cached
file, near-zero per-page cost); verify Microdot serves `.svg`/`.css` MIME
correctly, add explicit routes if not. Fallback: inline the 3 critical icons.
No emoji anywhere.

**Nav snippet**: byte-identical HTML on every page + 3-line JS that highlights
the item matching `location.pathname` (no per-page divergence). Active page
gets their highlighted-row treatment.

**Rollout**: D0 builds shell (dash.css + icons.svg + snippet) + `/admin` as the
proof page; D1–D9 pages use it from birth; D10 retrofits the 4 most-used old
pages (`/`, `/functions`, `/agent`, `/stats`) to shell nav + tokens (other old
pages keep working untouched). Static regression test per page: sidebar
present, active highlight correct, zero native dialogs, `node --check` clean —
plus the established local-browser GO (screenshots compared against dashref/
vibe: sidebar, stat cards, badges, cream buttons, mono theme, mobile collapse
at 390px width).
- RAM: pages are static files (zero heap); APIs reuse capped helpers (search 2KB, journey feed, capped lists). Counters are ints. No new background tasks (no new tick loops — reuse cron 60s if anything periodic is ever needed; nothing planned needs it).

## 7. Phases (each: code + pytest + local browser GO + device deploy, per established pipeline)

- **D1 Status landing** (`/admin` + banner logic; read-only APIs only). Tests: banner thresholds (heap verdict mapping, file-size surfacing), page markers.
- **D2 Sessions + D3 Logs** (two read-only pages, one phase; search + tail + export links). Tests: API coexistence (tail/search/export), markers, autorefresh toggle present.
- **D4 Stats counters + D5 Keys/Config-touchups** (backend 4 + `/keys` page + agent-page hints). Tests: counters increment/reset, redaction (raw secrets NEVER in any GET), markers.
- **D6 Cron page + `edit` op + D7 Skills page** (heaviest UI: modals for edit/propose/approve). Tests: edit validation/reschedule, propose→approve flow via UI-used ops, markers, no-dialogs grep.
- **D8 Channels + D9 System** (pairing UI, backup download redaction test, prune, verified-reset button). Tests: redaction matrix (every secret field), prune keep-N, reset-semantics doc-test, markers.
- **D10 Final**: full matrix re-verify on device (all pages 200 open+locked, cron job round-trip then removed, backup downloads, tg still dormant), update `docs/` + AGENTS.md deltas, close the plan.

## 8. Exit criteria

`/admin` shows vitals + banner correctly (incl. forced wrong-build text path on host); sessions searchable + exportable; logs tail live; stats counters move with use; keys page never leaks a secret (automated redaction matrix green); cron fully managed from UI; skills proposed→approved from UI; Telegram paired from UI (needs user token — same pending action as Phase 8); backup downloads with secrets redacted; suite green; browser GO before each device deploy.

## 9. Open decisions

1. `/` stays chat (recommended) vs Hermes-style status landing? 2. Backup: download-only v1 (recommended) vs restore too? 3. `disabled_skills[]` if bytes allow? 4. Drop list if flash tight (recommend: keys→agent, logs→API-only)?
