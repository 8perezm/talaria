# Mini Hermes Agent — Build Plan (ESP32-S3 + MicroPython)

Goal: evolve `esuyo-esp32-agent-python` into a **Mini Hermes Agent** — the same
*shape* as Nous Research `hermes-agent` (learning loop, skills, sessions,
cron, delegation, gateway), re-scaled to an ESP32-S3 with 16MB flash / ~8MB
PSRAM (SPIRAM_OCT firmware). Nearly the same capabilities, honest
miniaturization where hardware forces it (see §2 + `parity-matrix.md`).

Grounding docs: `docs/hermes-agent-summary.md`, `AGENTS.md`.
Hermes reference clone: `C:\Users\miguel\AppData\Local\Temp\opencode\hermes-agent`.

## 1. Baseline (what exists today — do not regress)

- **Loop** (`llm.py`): `callLLMWithTools` — 3 iters, ≤20 calls/iter,
  `agent.max_tokens` (default 4000; chat replies stay at 800), per-tool 30 s
  advisory timing, history 8 turns, msg cap 1500 chars, final cap 3500.
  Buffered path `_post_raw` (HTTP/1.0, Content-Length, 45s); SSE path
  `streamChat` (HTTP/1.1 chunked, `data:{"delta"}` events). Raw sockets
  (urequests has no timeout). IPv4-first DNS cache, SNI, gc+backoff retries.
- **Tools** (10/32 slots, `tools/registry.py` append-only, bitmask in
  `config.tools_mask`): `get_status, gpio_write, gpio_read, adc_read,
  wifi_scan, mem_save, mem_read, restart_device, blink, web_fetch`.
  Contract in `tools/README.md` (`TOOL{name,ui_hint,description,parameters,
  run,max_result_chars}`).
- **Memory**: `memory.txt` 4KB (`- fact` lines, ≤500 chars) + `chatlog.jsonl`
  32KB (1500 chars/role, one write/turn, last-8 injection, SSE path logs,
  clear via `POST /api/memory {clear_log:true}`).
- **Prompt** (`agent_tools.buildSystemPrompt`): identity + enabled-tools +
  full-knowledge clause (keep verbatim — it fixed "I have no knowledge") +
  memory ≤1200 chars + live snapshot `[ip up heap rssi]`.
- **Server** (`server.py`, Microdot asyncio): 7 pages + `/files` explorer +
  `/stats`; `GET/POST /api/{status,stats,auth,scan,wifi,agent,models,config,
  debug-raw,tools,memory,logs,files*,reset}` + `POST /api/chat,/chat-stream,
  /update`. Auth `Bearer/X-Auth-Token`, downloads accept `?token=`.
  Caps: 100KB read / 200KB write, binary download-only. `/update` blocklist
  (`config.json(.tmp)`, `memory.txt`, `chatlog.jsonl`). No native dialogs.
- **Config** (`config.json`, gitignored): wifi, endpoint, key, model,
  auth_token, tools_mask. Atomic save (tmp+rename).
- **Tests**: `python -m pytest tests/ -q` (host, `tests/stubs.py`).
- **Deploy**: serial UART port (was COM11 — verify), one `mpremote cp` per
  file + `os.stat` size assert, soft-reset, HTTP verify on the address the
  boot log printed (`WiFi OK: <ip>`, DHCP — pass it as `-DeviceHost`);
  `Bearer testtest`. Full rules in `AGENTS.md`.

## 2. Hard constraints (read before designing)

1. **SPIRAM_OCT firmware only** (`gc.mem_free()` must read ~8,000,000).
   `esp-aes: Failed to allocate memory` / mid-stream TLS wedges = wrong build,
   not network. Check first, theorize later.
2. **32-tool bitmask cap** (`tools_mask` int; registry order append-only).
   Slot budget in §4 — every new tool must fit; prefer action-param tools
   (`memory{action,target,…}`) over one-tool-per-verb.
3. **RAM discipline**: request bodies stay small (today ~16KB max);
   read files in chunks; `gc.collect()` around TLS; keep tool results ≤1–2KB.
4. **MicroPython limits**: utf-8/ascii only (parse HTTP on bytes); set socket
   timeout *before* `ssl.wrap_socket` (SSLSocket has no `settimeout`); clock
   epoch is 2000 (`_PLAUSIBLE_TIME`); no `sqlite3`, no threads (use
   `uasyncio`), no `iso-8859-1`.
5. **Flash wear**: one write/turn pattern; cron tick must not write unless due.
6. **No REPL tourism** on a healthy device (Ctrl-C kills the server).

## 3. Target architecture (mini, same boxes as Hermes)

```
Surfaces: web UI (7 pages+journey) | Telegram poller | (later: 2nd platform)
                     \                /
              gateway.py — session keys mini:{platform}:{chat},
                           allowlist, busy-guard, delivery
                                |
                           agent_core.py — run_conversation():
                             prompt.py (tiers) -> providers.py (primary+fallback)
                             -> llm._post_raw/streamChat -> dispatch (registry)
                             -> budgets -> compression.py -> persist
                                |                         |
                    persist: memory.py, skills.py,     tools/ (registry,
                    sessions.py (jsonl), cron.py        +13 new, §4)
```

New modules (all MicroPython-safe, host-testable via stubs):

| Module | Hermes original | Mini job |
|---|---|---|
| `prompt.py` | `prompt_builder.py` | tiered prompt assembly (stable/context/volatile) |
| `providers.py` | `runtime_provider.py` | primary + 1 fallback endpoint/model, failover on 429/5xx/transport fail |
| `agent_core.py` | `conversation_loop.py` | thin orchestrator over existing `llm.py` loop (budgets configurable) |
| `memory.py` | `memory_manager.py` | two stores + usage % + add/patch/remove + dup-reject + overflow-batch error |
| `skills.py` | `skill_commands.py` | single-file `skills/<name>.md`, L0 index / L1 full, `skill_manage` semantics |
| `sessions.py` | `hermes_state.py` | keyword search over jsonl, `/new` rotation, journey feed |
| `cron.py` | `cron/` | ≤5 jobs, 60s tick, agent-run + deliver to log/webhook/Telegram |
| `gateway.py` | `gateway/run.py` | unify web+Telegram ingress, auth, busy guard |
| `checkpoint.py` | checkpoints | `.bak` snapshot before writes + rollback API |
| `exec_py.py` (tool) | `execute_code` | constrained exec (no `machine/network`, time+output caps) |

## 4. Tool slot budget (10 used → 23 planned, cap 32)

Keep `mem_save/mem_read` as compat aliases (no new slots). New tools,
append-only in this order: `memory`(11), `skills_list`(12), `skill_view`(13),
`session_search`(14), `cron`(15), `todo`(16), `delegate_task`(17),
`exec_py`(18), `read_file`(19), `write_file`(20), `patch_file`(21),
`search_files`(22), `web_search`(23). `clarify`, `rollback` stay API/text-only
(no slots). Remaining headroom: 9 slots.

## 5. Phase plan (ship + verify each phase on device)

### Phase 0 — Baseline + doctor (no behavior change)
Add `GET /api/doctor`: `gc.mem_free`, firmware/PSRAM verdict, STA/AP+IP,
NTP plausibility, DNS resolve of endpoint host, upstream reachability timing
(PC-vs-device split in seconds), flash sizes of state files. Back up
`config.json`+`memory.txt`+`chatlog.jsonl` (base64 via REPL) before Phase 1.
Tests: `test_doctor.py` (thresholds, byte-header parsing).
Device: `/api/doctor` green, `/api/chat hello` 200 in ~2–4s.

### Phase 1 — Prompt tiers + provider fallback
- `prompt.py`: `buildMiniPrompt()` → `[stable]` identity+tools+knowledge clause
  +skills index, `[context]` optional `/.context.md` (≤1KB) + frozen memory
  snapshot, `[volatile]` live dev snapshot + time + budget warnings.
- `providers.py`: `resolveProviders()` → primary + fallback (endpoint,key,model
  from `config.json` `fallback_*` keys, setup via `/agent`); failover on
  429/5xx/transport error, one retry on fallback, then honest error text.
- `agent_core.py`: wrap `callLLMWithTools` with configurable
  `max_iters` (default 3, max 5) + per-call result caps; no loop-logic fork.
- Tests: tier ordering, frozen-snapshot stability within a turn, failover on
  429 then success, `tools_mask` auto-enable for new tools (existing behavior).
- Device: kill primary (bad key) → fallback answers; prompt contains all tiers.

### Phase 2 — Memory v2 (Hermes §7.1 shape)
- `memory.py`: `memory.txt` becomes device store (cap 2200 chars, Hermes parity)
  + new `user.txt` (cap 1375). Headers show `% used + n/m chars`; entries split
  on `- ` lines. Actions `add/patch/remove{target:(device|user)}` with unique-
  substring match, exact-dup reject, injection scan (block `import machine`,
  socket exfil patterns, invisible Unicode), overflow → error naming exact chars
  to free (model retries as one freeing+adding batch).
- `memory` tool (slot 11); `mem_save/mem_read` delegate to it. Migration: keep
  existing `memory.txt` content, trim oldest-first to 2200.
- Optional `memory.write_approval` flag → stage to `pending_mem.json`, review in
  `/functions` modal (`/api/memory pending|approve|reject`).
- Tests: caps, patch/remove matching, overflow math, migration trim.
- Device: add→persist→new-turn visible; overflow error actionable.

### Phase 3 — Skills mini (Hermes §7.2 shape, single-file)
- `skills/` dir (LittleFS), ≤12 skills, each `skills/<name>.md` ≤3KB:
  `# Title / When to use / Procedure / Pitfalls / Verification` + one-line
  `// desc:` header for the index.
- Prompt carries L0 index only (names+descs, ≤1KB); `skills_list` returns index,
  `skill_view{name}` returns full file; agent loads on demand.
- `skill_manage` semantics inside `skill_view`? No — separate `skill_manage`
  action param on `skills_list`? Decide: implement `skill_manage` as **API-only**
  (`POST /api/skills {action:create|patch|delete,…}`) + agent tool `skills_list`
  read-only, to save slots; agent-proposed skills go through `write_approval`
  staging (`pending_skills/`) + modal approve in `/files` or new `/skills` page.
  `/learn <text|url>`: agent drafts SKILL.md via normal turn, saved staged.
- Bundles: `bundles.json` `{name:[skills]}` → expand on `/bundle <name>` in chat.
- Tests: index budget, view caps, quarantine scan blocks injection skill.
- Device: create skill via chat → staged → approve → next turn L0 lists it →
  `/skillname` loads it.

### Phase 4 — Sessions: search, /new, journey
- `sessions.py`: `session_search{q}` keyword scan over `chatlog.jsonl` (and
  rotated `chatlog.prev.jsonl`), returns matching turns with neighbors;
  `session_search` tool (slot 14). Session keys `mini:{platform}:{chat_id}`
  (Hermes: `agent:{ns}:{platform}:{chat_type}:{chat_id}` via
  `build_session_key()` — ours drops ns/type: single profile, no threads).
  Branch/rewind explicitly deferred — single active + `.prev` only.
  `POST /api/memory{clear_log:true}` = `/new`
  (keep `memory.txt`/`user.txt`/skills — same as Hermes). Rotation: on clear,
  rename current log to `chatlog.prev.jsonl` (single generation, flash-cheap).
- `GET /api/journey`: time-ordered feed (memory mtimes + skill files + log
  rotations) → tiny timeline on `/stats` or new `/journey` section.
- Trajectory export: `GET /api/trajectory?format=sharegpt` (for future training).
- Tests: search ranking/neighbor windowing, rotation preserves memories.
- Device: old fact found via search after `/new`; journey shows entries.

### Phase 5 — Cron mini (≤5 jobs)
- `cron.py` + `cron.json`: `{id,prompt,every_s,next_run,enabled,deliver:(log|
  webhook_url|telegram)}`. `uasyncio` tick 60s in `main.py`; due job runs
  `agent_core` with attached skills context (no history), appends result to log
  + delivery target; updates `next_run`; never writes when idle.
- `cron` tool (slot 15): `add/list/pause/resume/remove/run_now`.
  UI: section on `/agent` or `/stats` + `GET/POST /api/cron`.
- Tests: due computation, pause/resume, disabled writes nothing.
- Device: 2-min test job fires twice, delivers to log; survives soft reset
  (state in `cron.json`).

### Phase 6 — Delegation + constrained exec
- `delegate_task{task,tools_allow}` (slot 17): one level only, sequential
  (no threads), child gets fresh history + restricted toolset (default: no
  `gpio_write/restart_device`), ≤2 per parent turn, child budget ≤10 iters
  (Hermes default 250 — unaffordable over device TLS), result capped 1KB into
  parent context. Child exit reasons mirror Hermes
  (`completed|max_iterations|interrupted|error`) in the result envelope. `todo{op:list|add|done}` (slot 16) as parent-local plan state
  (in-memory + mirrored into turn, not flashed).
- `exec_py{code}` (slot 18): sandboxed `exec` with `machine/network/os` blocked
  (byte-scan import list), timeout via tick budget, output cap 1KB. Approval:
  disabled by default in `tools_mask`; enable on `/functions` deliberately.
- Tests: nesting refused, allowlist enforced, blocked-import matrix.
- Device: "read pin 4 twice and average" style multi-step collapses into 1–2
  upstream calls.

### Phase 7 — Files as tools + checkpoints
- Tools (slots 19–22): `read_file{path}`, `write_file{path,content}`,
  `patch_file{path,old,new}`, `search_files{pattern}` — reuse server's
  `_fs_*` helpers (move to shared `fsutil.py` imported by both), same
  100KB/200KB caps, `config.json/memory/chatlog/cron.json` never writable.
- `checkpoint.py`: rotating `.bak` (one per path, ≤8 total) before every
  `write_file/patch_file`/upload; `POST /api/rollback{path}` restores.
- Tests: caps, blocklist, backup rotation count.
- Device: agent edits a `www/` label → `.bak` exists → rollback restores.

### Phase 8 — Gateway: Telegram + unified ingress
- `gateway.py`: `handleIngress(platform,chat_id,text)->reply` used by both
  `/api/chat` and the Telegram poller. Session key `mini:{platform}:{chat_id}`.
  `tg.json` (bot_token, allowlist[] — gitignored, `/update`-blocked);
  poller task: short-poll `getUpdates timeout=5` every ~30s (raw-socket GET
  helper in `llm.py`, same timeout discipline), `offset` persisted in tg state.
- Busy guard: one in-flight turn per session; second message → "working…"
  receipt (queued note injected next turn); `/stop` not feasible mid-TLS —
  document stop-at-turn-boundary.
- Pairing: unknown chat → reply "not paired" + log chat_id; owner adds via
  `/api/gateway{allow:[…]}` (auth required).
- Tests: key format, allowlist deny, busy-guard interleave, offset persist.
- Device: Telegram round-trip works; web chat unaffected; unpaired chat refused.

### Phase 9 — Polish + parity UI
- `/functions`: group tools by toolset (device, memory, skills, sessions,
  files, web, agent) mirroring Hermes toolsets; per-surface note (gateway tools
  hidden from web prompt when Telegram-only).
- `/stats` or `/journey`: journey timeline; `/docs`: Mini-Hermes skill/memory/
  cron how-to; chat composer: `/new /skills /cron /bundle` slash shortcuts.
- `GET /api/v1/models` mini + trajectory export link (stretch: OpenAI-compat
  chat passthrough — only if RAM allows).
- Full suite green, `docs/` updated, AGENTS.md deltas merged (new files, caps,
  slot table, cron/Telegram ops).

## 6. Test + deploy discipline (every phase)

- Host: `python -m pytest tests/ -q` after every edit; new file →
  `tests/test_mini_<name>.py` with stubs (+ `_FS_ROOT` override for fs).
- MicroPython-compat grep: no `iso-8859-1`, no `SSLSocket.settimeout`,
  no `alert|confirm|prompt(` in `www/`.
- Deploy: verify COM port → per-file `mpremote cp` + `os.stat` assert →
  soft-reset → banner + `WiFi OK` → `/api/doctor` → `/api/chat hello` 200.
- Never wipe `config.json`/`memory.txt`/`user.txt`/`chatlog*.jsonl`/`cron.json`/
  `tg.json`/`skills/` (extend `/update` blocklist as files are added).

## 7. Risks

| Risk | Mitigation |
|---|---|
| TLS heap wedge mid-stream (old symptom) | keep bodies small, gc around calls, fallback provider, `doctor` firmware check |
| Tool-slot exhaustion (32) | §4 budget, action-param tools, API-only for admin verbs |
| Flash wear (cron/skills writes) | write-on-change only, caps, single-generation rotation |
| Telegram long-poll RAM/TLS churn | short polls, 30s cadence, single socket at a time |
| Model never calls `memory`/skills (weak tool-callers) | explicit verbs in prompt, `/learn` + approval UI, journey makes gaps visible |
| Scope creep to full Hermes | §8 non-goals enforced per phase review |

## 8. Non-goals (v1)

Docker/SSH/Modal backends, browser automation, TTS/vision/image-gen, MCP
servers, multi-model mixture, desktop/Electron app, ACP/IDE integration,
prompt-caching directives (no Anthropic-native path on device), multi-profile
(`-p`) isolation. Stubs/deferred, not dead — revisit only after Phase 9 green.

## 9. Open decisions (default in bold)

1. Telegram as first gateway platform (**yes** / web-only)? 
2. Two memory stores (**yes**, Hermes-parity caps / keep single 4KB)?
3. `skill_manage` agent-writable (**staged+approve** / direct)?
4. Cron delivery targets (log + **webhook** + Telegram)?
5. `/update` OTA stays manual upload (**yes** / version-check)?

## 10. Phase exit criteria → "Mini Hermes done"

`/api/doctor` green; fallback answers with primary broken; two-store memory
with usage % + overflow guidance; ≥3 agent-created skills through
staged approval; search recalls pre-`/new` facts; cron job delivers twice
across reset; delegated multi-step task ≤2 upstream calls; file edit +
rollback verified; Telegram round-trip from allowlisted chat; full host suite
green; `parity-matrix.md` all P1 rows green.
