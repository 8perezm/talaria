# ESP32 Agent — MicroPython port

A chat harness on your ESP32, built in **MicroPython + Microdot** instead of C++/Arduino.
Same functionality as [`esuyo-esp32-agent`](../esuyo-esp32-agent): ears, hands, memory,
and the same browser UI + JSON API — you can ask it to blink lights, read pins,
remember facts, scan WiFi, and fetch the web.

> Port of the C++ firmware. Behaviour, routes, and all 10 tools are preserved;
> platform differences (config storage, update mechanism, mDNS) are noted below.

## Features (parity with C++)

- **Phone-friendly setup:** first boot creates open `ESP32-Agent-Setup` AP with
  wildcard DNS captive portal. Pick home WiFi + paste AI endpoint in the browser.
- **Chat in browser:** same 7 pages (`/`, `/setup`, `/wifi`, `/agent`, `/functions`,
  `/docs`, `/update`) served from `www/*.html` via Microdot `send_file`.
- **Same 10 tools:** `get_status`, `gpio_write`, `gpio_read`, `adc_read`,
  `wifi_scan`, `mem_save`, `mem_read`, `restart_device`, `blink`, `web_fetch`.
- **Same APIs:** `/api/status`, `/api/auth`, `/api/scan`, `/api/wifi`, `/api/agent`,
  `/api/models`, `/api/config` (legacy), `/api/chat`, `/api/chat-stream` (SSE),
  `/api/debug-raw`, `/api/tools`, `/api/memory`, `/api/reset`, `POST /update`.
- **Same auth:** optional device token (`Bearer` / `X-Auth-Token`), AP setup stays open.
- **Same memory:** `/memory.txt` (4KB) + `/chatlog.jsonl` (32KB) on flash, one write
  per turn, last-8-turns context injection, system prompt lists only enabled tools.
- **Conversation survives a refresh:** every completed turn — streamed or tool-driven —
  is appended to `/chatlog.jsonl`. The chat page rebuilds the transcript from
  `/api/memory?tail=20` on load, and the device injects the persisted turns into the
  next request whenever the browser sends no history. A **Clear** button in the
  composer asks for confirmation in an in-page dialog, then wipes the on-screen
  transcript and the device chat log (saved memory facts stay), so the next turn
  starts with no prior context.

## What changed (MicroPython realities)

| C++ | MicroPython port |
|-----|------------------|
| NVS `Preferences` (`esp32agent` ns) | `config.json` in filesystem (inspectable via REPL) |
| Arduino `WebServer` + `DNSServer` | Microdot (asyncio) + ~40-line UDP wildcard DNS in `net.py` |
| `PROGMEM` HTML in `web_ui.h` | `www/*.html` files (same markup; `/update` reworded for `.py` upload) |
| `Update.h` firmware.bin OTA + ArduinoOTA | `POST /update` saves `.py`/`.html`/`.json`/`.txt`/`.mpy` files then reboots; **MicroPython firmware itself is flashed once over USB** |
| mDNS `esp32-agent.local` | best-effort only (core MicroPython has no mDNS) — use the IP from serial |
| `HTTPClient` + `WiFiClientSecure` (insecure) | raw `socket` + `ssl` (MicroPython has no cert store; TLS verification none, same as C++). HTTP/1.0 for buffered requests, HTTP/1.1 + chunked decode for SSE; 15–45 s timeouts |
| `/api/chat-stream` true socket streaming | true streaming too: `stream:true` over HTTP/1.1 raw socket with incremental `Transfer-Encoding: chunked` decode; same `{"delta"}` / `{"reasoning"}` / `{"need_tools":true}` / `[DONE]` contract |
| `/api/scan` non-blocking async + 202 | blocking scan (~2s) + 30s cache; always `200` (UI already handles both) |
| Pin allowlists (classic ESP32) | S3-primary + classic-compat (`agent_tools.pinCanWrite/Read/ADC` auto-detect via `os.uname()`; S3 excludes USB 19/20 and flash 26-32) |

## Prerequisites

- **ESP32-S3 board** (tested target; classic ESP32 also works) + USB cable.
- **MicroPython firmware** (recent S3 build with PSRAM + LittleFS) flashed once.
- **Python 3 + mpremote** on your PC: `pip install mpremote esptool`.
- 2.4 GHz WiFi, phone/laptop browser, OpenAI-compatible endpoint + key + model.

## Installation

```powershell
# 1) Flash MicroPython once (example — match COM port + .bin you downloaded):
esptool --chip esp32s3 --port COM9 erase_flash
esptool --chip esp32s3 --port COM9 write_flash -z 0 ESP32_GENERIC_S3-202510XX.bin

# 2) Install Microdot onto the board (once). `mip install github:...` does NOT
#    work for this package — copy the files under /lib/microdot instead, from
#    https://raw.githubusercontent.com/miguelgrinberg/microdot/main/src/microdot/
#    (__init__.py, microdot.py, multipart.py, helpers.py)
#    e.g. mpremote connect COM9 cp microdot.py :/lib/microdot/microdot.py

# 3) Copy this project (repeat after every edit):
powershell -File deploy.ps1 -Port COM9
# equivalent manual: mpremote connect COM9 cp -r config.py agent_tools.py llm.py net.py server.py main.py boot.py tools www :

# 4) Watch boot logs, note the IP:
mpremote connect COM9 reset
mpremote connect COM9 repl
# expect: === Agent boot ===, WiFi OK: 192.168.x.x  OR  AP started: ESP32-Agent-Setup
```

Then open `http://<IP>/` (or `http://192.168.4.1/wifi` for first setup) and follow
the same 4-step flow as the C++ README: join `ESP32-Agent-Setup` → save WiFi →
rejoin home WiFi → `/agent` endpoint/key/model → chat.

## Project structure

```
esuyo-esp32-agent-python/
  main.py            # boot: config -> fs -> wifi/AP -> mdns -> serve (port 80)
  boot.py            # gc tuning
  config.py          # config.json settings + URL/key helpers (was config.h/.cpp)
  net.py             # WiFi STA/AP + wildcard DNS + watchdog (was net.h/.cpp)
  agent_tools.py     # memory/log, pins, prompt, tools dispatch (was agent_tools.*)
  tools/             # one module per tool + registry.py (was src/tools/)
    tool_get_status.py, tool_gpio_write.py, tool_gpio_read.py, tool_adc_read.py,
    tool_wifi_scan.py, tool_mem_save.py, tool_mem_read.py, tool_restart.py,
    tool_blink.py, tool_web_fetch.py
  llm.py             # OpenAI bridge + 3-iteration tool loop (was llm.h/.cpp)
  server.py          # Microdot app: all pages + JSON APIs + SSE + /update (was routes.*)
  www/               # 7 HTML pages (was web_ui.h PROGMEM blobs)
  mip_install.py     # on-device Microdot installer fallback
  deploy.ps1         # USB deploy script
  tests/             # host-side (CPython) unit tests with hardware stubs
```

## Configuration

All settings live in `config.json` on the device (blank keeps saved):

- Join AP `ESP32-Agent-Setup` → `http://192.168.4.1/wifi` → Scan → Save & Reboot.
- Rejoin home WiFi → `http://<IP>/agent` → endpoint base (`/chat/completions` is
  appended), API key, model → Save (no reboot).
- Optional device password on `/setup` (min 8 chars). Same `Bearer` header scheme
  as C++; browser OTA (`/update`) honours it too.

Handy pages: `/` chat, `/setup` hub, `/wifi`, `/agent`, `/functions` (tool toggles),
`/docs`, `/update` (`.py` upload). Full API shapes match the C++ `docs/api.md`.

## Usage

Same quick-start as C++:

```text
what is your heap, uptime and IP?
scan for nearby wifi networks
blink GPIO 2 five times
read GPIO 34 as analog
remember that my plant is a basil
what did I tell you about my plant?
fetch https://example.com and summarize it in one line
```

Streaming + fallback, *Thinking* block, model picker (`GET /api/models` proxied
from your endpoint), memory panel, and `POST /api/reset` factory wipe all behave
as documented in the C++ repo.

## Development

- Host tests (no hardware): `pip install microdot pytest`, then `pytest tests/ -q`.
  Hardware modules (`machine`, `network`, `esp32`, `urequests`, `uasyncio`) are
  stubbed in `tests/stubs.py`.
- Add a tool: copy `tools/_template.py.sample` → `tools/tool_x.py`, fill 3 spots,
  append to `tools/registry.py` (END only — index = bit in `tools_mask`).
- Edit UI: change `www/*.html`, redeploy (`deploy.ps1`), hard-refresh browser.
  No build step — files run in place.
- Debug: REPL logs (`[agent]`, `[tool]`, `[chat]`), `GET /api/status`,
  `GET /api/debug-raw?message=...` (raw upstream body, key never leaks).

## License

MIT — Copyright (c) 2026 Miguel Perez. See [LICENSE](./LICENSE).
