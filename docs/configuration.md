# Configuration

All settings live in `config.yaml` at the filesystem root. It is plain
block-style YAML (see `yamlish.py`), hand-editable over the Files editor, a
REPL, or `mpremote cp`. The Config page in the dashboard edits the same file
through a schema-driven form plus a raw-YAML view.

## Sections

| Section | Keys | Notes |
|---|---|---|
| `agent` | `endpoint`, `model`, `api_key`, `max_iters` (1–5, default 3) | Primary OpenAI-compatible provider. `endpoint` is the base URL — `/chat/completions` and `/models` are appended (`config.py:chatCompletionsUrl/modelsUrl`). |
| `fallback` | `endpoint`, `model`, `api_key` | Secondary provider, used only when the primary fails. |
| `network` | `wifi_ssid`, `wifi_pass`, `mdns_name` (default `talaria-agent`), `ap_ssid` (default `Talaria-Agent-Setup`) | Station network + setup AP + discovery name. Changes need a reboot (`restart_required: true`). |
| `chat` | `entry_chars` (500–20000, default 4000), `restore_turns` (1–60, default 20), `log_max_kb` (64–4096, default 320), `log_keep_kb` (default 200, must leave 32 KB headroom) | Per-message retention, transcript restore depth, rolling-log rotation budget. |
| `theme` | `color_scheme`, `font_headers(+_size)`, `font_body(+_size)`, `font_mono(+_size)` | Dashboard look. Browser-applied, no restart. |
| `security` | `auth_token`, `memory_write_approval` (default off), `skills_write_approval` (default on) | Dashboard token + agent write-approval toggles. |
| `tools` | `mask` | Bitmask of enabled tools (bit = index in `app/tools/registry.py`; managed on the Tools page). |

Minimal example:

```yaml
agent:
  endpoint: https://api.deepinfra.com/v1/openai
  model: deepseek-ai/DeepSeek-V4.1-Flash-1017
  api_key: sk-...
  max_iters: 3
network:
  wifi_ssid: HomeNet
  wifi_pass: ...
chat:
  entry_chars: 4000
  restore_turns: 20
security:
  auth_token: ...
  skills_write_approval: true
```

## How it works (code map)

- `config_schema.py` is the single registry: field key, category, group, type
  (`string`/`number`/`boolean`/`secret`/`select`/`readonly`), label, description,
  default, min/max, `restart`. Add a setting there and read it in `config.py` —
  the Config page renders it automatically (no per-setting UI code).
- `config.py:loadConfig()` reads `config.yaml`, migrates a legacy `config.json`
  once (kept as `config.json.bak`), and applies clamped values to module
  globals (`cfgSsid`, `cfgEndpoint`, …). A typo in one field falls back to that
  field's default at boot; saves stay strict (API returns 400).
- `yamlish.py` parses the small YAML subset the device needs (maps, block and
  inline lists, inline maps, quoted strings, comments, bool/int/float/null).
  It rejects anchors, tags, and block scalars.
- Writes are atomic (temp file + rename). `config.dump_doc` renders commented
  YAML in schema order and preserves unknown/hand-added keys, so a form save
  never deletes a setting it does not know about.

## API

- `GET /api/config/form` — schema + current values (secrets blank, masked
  placeholders). `POST /api/config/form` — `{values: {"dotted.key": value}}`;
  blank secrets keep the stored value; network changes return
  `restart_required: true`.
- `GET /api/config/yaml` — redacted raw text (`?secrets=1` reveals).
  `POST /api/config/yaml` — `{yaml}` full replacement; masked `****`
  placeholders are swapped for live secrets, and byte-identical normalisation
  writes the original text back so hand-written comments survive.
- Legacy flat endpoints still work and patch the same nested document:
  `GET/POST /api/config`, `/api/agent`, `/api/wifi`, `POST /api/auth`
  (token min 8 chars).

## Auth model

- Optional device token (`security.auth_token`). When set (and not in AP setup
  mode), every `/api/*` and `/update` call needs
  `Authorization: Bearer <token>` or `X-Auth-Token: <token>`
  (`app/server.py:1442-1472`). Setup paths (`/setup`, `/wifi`, `/update` page)
  never redirect to login.
- Login page (`/login`): fixed username `admin`, password = auth token.
  `POST /api/login` is a stateless verifier — no cookies/sessions on the MCU;
  the browser keeps the token in `esp32_token` localStorage.
- `GET /api/backup` never emits raw `api_key`/`wifi_pass`/`auth_token`/
  `bot_token` (masked shapes only).
