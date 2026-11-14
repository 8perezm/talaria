# API Reference

Derived from `app/server.py` route handlers. All `/api/*` routes (except
`/api/auth` and `/api/login`) require auth when a device token is set and the
device is not in AP setup mode: `Authorization: Bearer <token>` or
`X-Auth-Token: <token>`. Downloads use `?token=` since plain links cannot set
headers. Error shape: `{"error": "..."}` with an HTTP status.

## Device & health

| Method & path | Purpose |
|---|---|
| `GET /api/status` | Heap, uptime, SSID/IP, endpoint/model, `tools_mask`, `auth_required`, `ap_mode` |
| `GET /api/stats[?i2c=1]` | Heap, flash, MCU temperature, RSSI, per-tool call counters |
| `GET /api/doctor` | Firmware/heap/config sanity report |
| `GET /api/auth` | `{auth_required, ap_mode, username}` |
| `POST /api/login` | `{username: "admin", password: <auth token>}` → `{ok}` stateless verifier |
| `POST /api/auth` | Set/clear device token `{token}` (min 8 chars, max 128) |
| `POST /api/reboot` | Safe soft reset (wipes nothing) |
| `POST /api/reset` | **Factory wipe** (deletes `config.yaml`, memory, all sessions) + reboot |
| `GET /api/backup` | Full state export; secrets always masked/redacted |

## Chat & models

| Method & path | Purpose |
|---|---|
| `POST /api/chat` | `{message, history?}` → full agentic turn (tool loop server-side) |
| `POST /api/chat-stream` | SSE: `data: {"delta"}` / `{"reasoning"}` … `{"need_tools":true}` + `[DONE]`; the browser falls back to `/api/chat` for tool turns |
| `GET /api/debug-raw?message=` | No-tools upstream echo (isolates provider problems) |
| `GET /api/models` | Provider catalogue via device-side TLS (can take ~6 s — fetched lazily) |
| `GET /api/agent` / `POST /api/agent` | Read/write endpoint, key, model, fallback, `max_iters` |
| `GET /api/config` / `POST /api/config` | Legacy flat config read/write |
| `GET /api/config/form` / `POST /api/config/form` | Schema + values / dotted-key save |
| `GET /api/config/yaml[?secrets=1]` / `POST /api/config/yaml` | Raw YAML view / full replacement |

## Conversations & memory

| Method & path | Purpose |
|---|---|
| `GET /api/sessions` | Conversations `{id, title, created, bytes, kind, active}` |
| `POST /api/sessions` | Start a conversation (new file on first turn) |
| `POST /api/sessions/activate` | Point the web UI at `{id}` |
| `POST /api/sessions/delete` | Delete a conversation (deleting the active one starts fresh) |
| `GET /api/sessions/export?id=<sid>[&token=]` | Plain-text download of one conversation |
| `GET /api/memory[?session=&tail=&activate=]` | Transcript tail (default: active conversation, `restore_turns` × 2 lines) |
| `POST /api/memory` | Append a memory fact |
| `GET /api/journey` / `GET /api/trajectory` | ShareGPT-format trajectory export |
| `GET /api/cron` / `POST /api/cron` | Schedules (optional `script` in `/workspace`, `no_agent` flag, `name` label) |
| `GET /api/skills` / `POST /api/skills` | Procedural memory list/create/view/delete + approval queue |
| `GET /api/gateway` / `POST /api/gateway` | Telegram pairing + allowlist |
| `GET /api/tools` / `POST /api/tools` | Tool registry grouped by toolset + enable mask |
| `GET /api/logs` / `POST /api/logs/clear` | Console tail (filter/pause in UI) |
| `GET /api/scan` | Nearby WiFi networks (blocking ~2 s, 30 s cache, always `200`) |
| `GET /api/wifi` / `POST /api/wifi` | Read/save station credentials |
| `GET /api/rollback` / `POST /api/rollback` | File `.bak` checkpoint list/restore |

## Files (`/opt/data` home) & system hatch (full flash)

| Method & path | Purpose |
|---|---|
| `GET /api/files?path=` | List dir (mono path, sortable Name/Size/Modified) |
| `GET /api/files/content?path=` | Read text file (100 KB cap; binary = download-only) |
| `GET /api/files/download?path=[&token=]` | Download blob |
| `POST /api/files/save` | `{path, content}` write (200 KB cap, `.bak` checkpoint) |
| `POST /api/files/mkdir` / `POST /api/files/delete` | Create dir / delete (refuses `opt`, `opt/data` — use `/api/reset`) |
| `POST /api/files/rename` / `POST /api/files/upload` | Rename / multipart upload (client-side text read) |
| `GET /api/system/files…` / `POST /api/system/files/…` | Same operations on full flash incl. `config.yaml` (validates + reloads) |
| `POST /api/ui/asset?path=` | Raw-body dashboard bundle push (`index.html`/`favicon.svg`/`assets/*`, ≤900 KB) |
| `POST /update` | Multipart `firmware` field: code/page files (`.py/.html/.json/.txt/.mpy/.js/.css/.svg/.md`; 900 KB `.js`/`.css`, 200 KB else), then reboot. Refuses device state |

## Tools (built-in, `app/tools/registry.py`)

`get_status`, `gpio_write`, `gpio_read`, `adc_read`, `wifi_scan`, `mem_save`,
`mem_read`, `restart_device`, `blink`, `web_fetch`, `memory`, `skills_list`,
`skill_view`, `session_search`, `cron`, `todo`, `delegate_task`, `exec_py`,
`read_file`, `write_file`, `patch_file`, `search_files`, `run_script`. Pin
allowlists are S3-aware (`agent_tools.pinCanWrite/Read/ADC` auto-detect via
`os.uname()`; USB 19/20 and flash 26–32 excluded).

`run_script` executes a workspace `.py` in-process as `__main__` with a 16 KB
source and 1 KB output cap (cron script jobs share the caps), so a script can
import and use the device's own modules. Build long scripts with
`write_file append=true` (≤4 KB per call, ≤16 KB per file) and inspect them
with `read_file`/`patch_file`; `search_files` defaults to `opt/data`.
