# Project Structure

Repository layout and what each part owns.

```
.
├── main.py / boot.py        Device entry point (runs at power-on) + GC tuning
├── server.py                HTTP app: SPA hosting, ~70 JSON/SSE routes, /update
├── agent_core.py            Agentic turn loop (prompt → tools → reply)
├── agent_tools.py           System prompt, tool dispatch, memory/log helpers
├── llm.py                   OpenAI-compatible bridge (buffered + SSE streaming)
├── providers.py / prompt.py Model catalogue helpers / prompt text
├── config.py                config.yaml load/save, clamps, secret masking
├── config_schema.py         Single registry of every setting (key/type/default)
├── yamlish.py               Small YAML-subset parser (maps, lists, scalars)
├── net.py                   WiFi STA/AP, wildcard DNS portal, NTP, DNS fallback
├── sessions.py              Conversation store (one JSONL file per conversation)
├── memory.py / skillstore.py Long-term memory + skills (with approval queues)
├── cron.py / todo.py / delegate.py  Schedules, task list, subagent delegation
├── checkpoint.py / fsutil.py File rollback snapshots / block-wise file readers
├── gateway.py               Telegram pairing + message polling
├── logbuf.py                In-memory console ring buffer (backs /api/logs)
├── exec_py.py, read_file.py, write_file.py, patch_file.py, search_files.py
│                            Workspace file tools (agent-facing)
├── tools/                   One module per built-in tool + registry.py
│   ├── registry.py          TOOL_REGISTRY (order = tools_mask bit; append-only)
│   └── tool_*.py            get_status, gpio_*, adc_read, wifi_scan, blink,
│                            web_fetch, mem_*, memory, skills_*, session_search,
│                            cron, todo/delegate/exec/read/write/patch/search
│                            live under their own top-level modules
├── ui/                      React 19 + TS + Tailwind dashboard source
│   ├── src/pages/           One file per route (Chat, Sessions, Files, Config…)
│   ├── src/components/      Shell, sidebar, primitives, markdown
│   ├── src/lib/             API client (serialised), polling hooks, theme
│   └── scripts/postbuild.mjs Gzip twins + cache-busted shell stamp
├── www/                     BUILD OUTPUT — served by the device, never hand-edit
│   ├── index.html           Shell (cache-busted `?v=<hash>`)
│   └── assets/app.js(.gz), app.css(.gz)  Whole app, one chunk + prebuilt gzip
├── tests/                   Host-side CPython suite, hardware stubbed (stubs.py)
├── scripts/esp_deploy.py    Multi-file USB upload + size verification CLI
├── deploy.ps1               Full deploy: optional UI rebuild + copy + reboot
├── mip_install.py / requirements.txt  On-device Microdot dependency note
└── docs/                    Developer docs (this folder)
```

## Notes

- **Device root vs repo root:** on flash, application files live at `/`
  (`server.py`, `tools/`, …), Microdot lives at `/lib/microdot/`, and all
  mutable user state lives under `/opt/data/` (sessions, `activity.jsonl`,
  `memory.txt`, `user.txt`, `cron.json`, `tg.json`, `skills/`,
  `pending_skills/`, `workspace/`). `config.yaml` stays at `/` and is owned by
  the Config page — the browser Files view cannot reach outside `/opt/data`.
- **System hatch:** `/api/system/files*` exposes full-flash list/read/save for
  maintenance; the normal Files UI stays scoped to `/opt/data` by construction.
- **Git-ignored device state** (`.gitignore`): `opt/`, `config.yaml`,
  `config.json*`, `memory.txt`, `user.txt`, `chatlog*.jsonl`,
  `activity*.jsonl`, `cron.json`, `tg.json`, `bundles.json`,
  `pending_mem.json`, `pending_skills/`. Never commit live secrets or logs.
- **`www/` is build output:** `npm run build` inside `ui/` regenerates it
  (see [Build & Deployment](./build-and-deployment.md)). Edit `ui/`, never `www/`.
- **Workspace:** agent-created chat files and cron scripts live under
  `opt/data/workspace/` (cron scripts are required to live there).
