# Development Guide

Local setup and day-to-day workflow for contributors. For flashing and release
deploys see [Build & Deployment](./build-and-deployment.md).

## Prerequisites

- Python 3 on the host (`python` = CPython; PowerShell on Windows).
- Host test deps: `pip install microdot pytest` (plus `pyserial`, `esptool`,
  `mpremote` for device work: `pip install esptool mpremote`).
- Node 20+ with npm (or pnpm) — only needed when changing the dashboard in `ui/`.
- An ESP32-S3 N16R8 board if you want on-device verification; most iteration
  happens host-side via the stubbed test suite.

## Host test loop (no hardware)

Hardware modules (`machine`, `network`, `esp32`, `urequests`, `uasyncio`) are
stubbed in `tests/stubs.py`, so the suite runs on plain CPython:

```powershell
python -m pytest tests/ -q
```

Run this after every edit. Conventions:

- Pure mapping/parsing helpers must stay hardware-free and pinned by tests
  (e.g. `tests/test_esp_deploy.py` for the deploy CLI, `tests/test_yamlish.py`
  for the YAML subset, `tests/test_micropython_compat.py` for codec/socket
  limits).
- API-shape changes go in `tests/test_api_contract.py`; SPA nav/route parity,
  house rules (no `alert`/`confirm`/`prompt`, no CDN, palette tokens, hand
  cursor) live in `tests/test_spa.py` — update the UI and the test together.
- New settings: add one field in `config_schema.py`, read it in `config.py`;
  the Config page renders it automatically. Mirror the four theme defaults in
  `config_schema.py` FIELDS, `config.py` `DEFAULT_THEME_*`,
  `ui/src/lib/theme.ts` `THEME_DEFAULTS`, and `ui/src/index.css` tokens.

## Incremental device workflow

Batch uploads into one CLI invocation (one tool call per batch, not per file):

```powershell
python scripts/esp_deploy.py app/server.py app/llm.py --reset
python scripts/esp_deploy.py www/assets/app.js www/index.html --reset
python scripts/esp_deploy.py --verify-only app/server.py app/llm.py
python scripts/esp_deploy.py --raw app/server.py app/llm.py --reset   # fallback path
```

- Specs are `LOCAL[:REMOTE]` (remote defaults to the repo-relative path).
- Parent dirs are created automatically; every file is size-verified
  (`os.stat(...)[6]` == local size) with one batched stat, ending in
  `SUMMARY ok=X fail=Y`. An echoed "cp ok" proves nothing — only size equality.
- The CLI auto-detects the CH343 UART bridge (`--port` overrides).
- Any REPL contact stops the app; always pass `--reset` (or press RESET) and
  then confirm over HTTP instead of via REPL.

## Debugging

- Serial log first: the `=== Agent boot ===` banner, `WiFi OK:` /
  `AP started:`, and `[ntp] time synced:` (full power cycle only — soft resets
  keep the RTC) tell you where boot got to.
- `GET /api/status` — heap, uptime, SSID/IP, endpoint/model, `tools_mask`.
- `GET /api/stats` / `GET /api/doctor` — heap, flash, MCU temperature, RSSI,
  per-tool call counters, firmware variant check.
- `GET /api/debug-raw?message=hi` — no-tools path; splits upstream problems
  from the agentic loop.
- Browser console: `window.__talaria` (live dashboard state) and
  `window.__talariaNet` (last 40 API calls with timings) — the fastest way to
  diagnose a stalled request on a device with no console.
- On-device check that the firmware variant is right:
  `import gc; gc.collect(); print(gc.mem_free())` must print ~8 000 000, not
  ~90 000.

## Coding standards

- **MicroPython limits are real:** only `utf-8`/`ascii` codecs exist (parse HTTP
  headers on bytes, never `b.decode("iso-8859-1")`); SSL sockets have no
  `settimeout()` (set the timeout on the plain socket before wrapping);
  `time.time()` counts from 2000-01-01 (NTP guard uses the year-2024 threshold).
  `tests/test_micropython_compat.py` pins these.
- **RAM discipline:** never `f.read()` an unbounded file — use the block-wise
  readers in `fsutil.py` (`read_jsonl_tail`, chunked rotation copies). One
  16 KB-block reader pattern keeps RAM flat regardless of log size.
- **Tool registry:** add tools by copying `app/tools/_template.py.sample`,
  filling the 3 spots, and appending to `TOOL_REGISTRY` in
  `app/tools/registry.py` — END only, never reorder (index = bit in `tools_mask`).
- **No blocking calls on the server path:** use the existing timeouts
  (15–45 s), keep `/api/models` lazy (fetch on picker open, never at page
  start), and keep `MAX_CONCURRENT = 1` in `ui/src/lib/api.ts` (the ESP32's
  lwIP drops extra SYNs under parallel bursts).
- **UI house rules** (pinned by `tests/test_spa.py`): no native dialogs
  (use the promise-based `useConfirm` modal), no CDN/fonts that break offline
  LAN use (sole carve-out: on-demand Google Fonts in `ui/src/lib/theme.ts`),
  keep the design tokens and square corners in `ui/src/index.css`.
- **Never touch by hand:** `www/` output, `*_test` device state listed in
  `.gitignore`, and the `/api/reset` wiring (factory wipe + reboot; the safe
  soft reset is `POST /api/reboot`).
