# Project Structure

Repository layout and what each part owns.

```
.
├── main.py / boot.py      Device entry points (MicroPython runs these by
│                          name — the only .py files at the root)
├── app/                   Application package (device: /app, on sys.path
│                          via main.py, so flat `import config` keeps working)
│   ├── server.py          HTTP app: SPA hosting, ~70 JSON/SSE routes, /update
│   ├── agent_core.py      Agentic turn loop (prompt → tools → reply)
│   ├── agent_tools.py     System prompt, tool dispatch, memory/log helpers
│   ├── llm.py             OpenAI-compatible bridge (buffered + SSE streaming)
│   ├── config.py / config_schema.py / yamlish.py
│   │                      config.yaml load/save, setting registry, YAML subset
│   ├── net.py             WiFi STA/AP, wildcard DNS portal, NTP, DNS fallback
│   ├── sessions.py / memory.py / skillstore.py
│   │                      Conversations, long-term memory + skills (approvals)
│   ├── cron.py / todo.py / delegate.py  Schedules, task list, delegation
│   ├── gateway.py         Telegram pairing + message polling
│   ├── checkpoint.py / fsutil.py / logbuf.py
│   │                      Rollback snapshots, block readers, /api/logs buffer
│   ├── exec_py.py, read_file.py, write_file.py, patch_file.py, search_files.py
│   │                      Workspace file tools (agent-facing)
│   ├── providers.py / prompt.py / mip_install.py
│   └── tools/             One module per built-in tool + registry.py
│       ├── registry.py    TOOL_REGISTRY (order = tools_mask bit; append-only)
│       └── tool_*.py      get_status, gpio_*, adc_read, wifi_scan, blink,
│                          web_fetch, mem_*, memory, skills_*, session_search,
│                          cron (todo/delegate/exec/read/write/patch/search
│                          live in app/ and register through the registry)
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
├── requirements.txt + app/mip_install.py  On-device Microdot dependency note
└── docs/                    Developer docs (this folder)
```

## Notes

- **Device root vs repo root:** on flash, only `boot.py`/`main.py` live at `/`;
  the application lives in `/app/` (`app/server.py`, `app/tools/`, … — imports
  stay flat because `main.py` puts `/app` on `sys.path`). Microdot lives at
  `/lib/microdot/`, and all mutable user state lives under `/opt/data/` (sessions, `activity.jsonl`,
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
