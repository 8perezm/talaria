# Architecture

How Talaria Agent fits together on the ESP32-S3: stack, boot sequence, request flow, and key modules.

## Stack

- **Device runtime:** MicroPython on ESP32-S3 (N16R8 board: 16 MB flash, 8 MB octal PSRAM).
  The `SPIRAM_OCT` firmware variant is required — it is the only build that can
  drive octal PSRAM, which is what gives the device its ~8 MB heap.
- **HTTP server:** Microdot with `uasyncio`, vendored on-device at `/lib/microdot/`
  (`__init__.py`, `microdot.py`, `multipart.py`, `helpers.py`).
- **LLM bridge:** `llm.py` talks to any OpenAI-compatible endpoint over a raw
  `socket` + `ssl` connection (buffered requests use HTTP/1.0; server-sent-events
  streaming uses HTTP/1.1 with incremental `Transfer-Encoding: chunked` decoding).
- **Dashboard:** React 19 + TypeScript + Tailwind v4 in `ui/`, compiled to static
  files in `www/` and served straight off flash. No server-side rendering.
- **Config:** nested YAML file `config.yaml`, schema-driven via `config_schema.py`
  with a small YAML subset parser (`yamlish.py` — no PyYAML on-device).
- **State:** user data lives under `/opt/data/` (sessions, memory, skills, cron,
  workspace). See [Project Structure](./project-structure.md).

## Boot sequence (`main.py` + `boot.py` + `net.py`)

1. `boot.py` runs first: enables GC, raises the GC threshold for PSRAM boards.
2. `main.py` prints `=== Agent boot ===`, imports `config`, `agent_tools` and the
   tool registry (`tools/registry.py:register_into_agent_tools`), then
   `config.loadConfig()` and `agent_tools.initAgentFS()`.
3. `net.connectWiFi(15000)` (`net.py:22`) tries the configured station network.
   - Success: keeps STA up, `ensure_dns()` (falls back to `8.8.8.8` if the LAN
     resolver fails), `syncTime()` (NTP — TLS needs a plausible date; the RTC
     boots at 2000-01-01 and `time.time()` counts from 2000-01-01 on this port),
     disables WiFi power-save for responsiveness.
   - Failure: `net.startAP()` brings up the open `Talaria-Agent-Setup` network
     (`AUTH_OPEN`, no password arg) plus a wildcard DNS task so any hostname
     resolves to `192.168.4.1` (captive portal).
4. `try_start_mdns()` is best-effort (MicroPython core has no mDNS — use the IP
   from the serial log).
5. `server.get_app()` builds the Microdot app; three background tasks start
   (WiFi watchdog every 30 s, cron tick every 60 s, Telegram poll every 30 s —
   `main.py:26-83`).
6. The server loop serves on `0.0.0.0:80` and restarts itself if it ever returns
   instead of dropping to the REPL (`main.py:131-141`).

## Request / data flow

```
Browser (SPA) ──Bearer/X-Auth-Token──▶ Microdot (server.py, :80)
                                          │  ├── /api/* JSON handlers
                                          │  └── /<path:path> catch-all → www/index.html
                                          ▼
                                   agent_core.py runTurn()
                                          │  builds system prompt (agent_tools)
                                          │  loops ≤ agent.max_iters tool rounds
                                          ▼
                                   llm.py ──raw socket+TLS──▶ provider
                                          /chat/completions (+ /models)
                                          ▼
                              tool dispatch (tools/registry.py → agent_tools)
                                          ▼
                              flash state (/opt/data/…) + GPIO/ADC/WiFi hardware
```

- **Chat:** `POST /api/chat` runs the full agentic loop server-side
  (`server.py:2133`, `agent_core.runTurn`). `POST /api/chat-stream`
  (`server.py:2214`) streams `data: {"delta"}` / `{"reasoning"}` events and
  emits `{"need_tools":true}` + `[DONE]` when the browser must fall back to
  `/api/chat` for the tool loop. `/api/debug-raw` (`server.py:2086`) is the
  no-tools path for isolating upstream problems.
- **Auth:** every `/api/*` route (except `/api/auth`, `/api/login`, setup
  pages) checks `is_authenticated()` — `Authorization: Bearer <token>` or
  `X-Auth-Token: <token>` (`server.py:1456-1472`). Auth is disabled while in AP
  setup mode (`server.py:1442-1445`). The login page is a stateless verifier:
  fixed username `admin`, password = device auth token (`server.py:70,1703`).
- **Config writes:** form saves (`POST /api/config/form`) and raw YAML saves
  (`POST /api/config/yaml`) go through `config.save_form()` / `save_raw_yaml()`,
  which normalize against `config_schema.py`, write `config.yaml` atomically
  (temp file + rename), and refresh the module globals. Network changes return
  `restart_required: true`. Secrets stay masked (`****`) unless revealed.
- **Files:** `GET/POST /api/files*` (`server.py:2878-3171`) is locked to the
  `/opt/data` user-data home. `GET/POST /api/system/files*`
  (`server.py:3173-3351`) is the separate full-flash surface (code + `www/`),
  with the same caps (100 KB read / 200 KB write) and `.bak` checkpoints.
- **Memory model:** each conversation is one append-only JSONL file under
  `opt/data/sessions/` plus `active.json` pointing at the web UI's current one
  (`sessions.py`). Cron output goes to the separate `opt/data/activity.jsonl`
  so scheduled jobs never pollute chat history. `GET /api/memory` restores the
  transcript; per-message size and rotation budgets are config-driven
  (`chat.entry_chars`, `chat.log_max_kb`, `chat.log_keep_kb`,
  `chat.restore_turns`).

## Key modules

| File | Role |
|---|---|
| `main.py` / `boot.py` | Boot, background tasks, self-restarting server loop |
| `server.py` | All HTTP routes (~70 handlers), auth, SPA + gzip static serving, `/update` |
| `agent_core.py` / `agent_tools.py` | Tool loop, system prompt, chat-log + memory helpers, tool enable mask |
| `llm.py` | Raw-socket OpenAI bridge, fallback provider, buffered + streaming paths |
| `tools/registry.py` | The 22-tool registry (index = bit in `tools_mask`; append-only) |
| `config.py` / `config_schema.py` / `yamlish.py` | Settings load/save/migrate, single field registry, YAML subset |
| `net.py` | STA/AP switching, wildcard DNS captive portal, NTP, DNS fallback |
| `sessions.py` / `memory.py` / `skillstore.py` | Conversations, long-term memory, skills (+ approval queues) |
| `cron.py` / `todo.py` / `delegate.py` | Scheduled turns (optional script step), task list, subagent delegation |
| `gateway.py` | Telegram pairing + polling |
| `fsutil.py` / `logbuf.py` | Block-wise JSONL readers, ring-buffer console log for `/api/logs` |
| `exec_py.py`, `read_file.py`, `write_file.py`, `patch_file.py`, `search_files.py` | Workspace file tools used by the agent |
| `providers.py` / `prompt.py` / `checkpoint.py` | Model catalogue helpers, prompt text, file rollback snapshots |
| `ui/` → `www/` | Dashboard source → device-served bundle (see [Build & Deployment](./build-and-deployment.md)) |
