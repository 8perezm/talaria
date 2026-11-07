# AGENTS.md — field notes for the next agent working this repo

MicroPython + Microdot port of `esuyo-esp32-agent` (C++/Arduino).
Target board on the bench: ESP32-S3, 16MB flash, 8MB embedded PSRAM, native USB.

## Board ownership + device URL

- **This board belongs to the agent for development purposes** — the user has
  assigned this ESP32-S3 to the agent, so use it freely for dev/test/deploy
  cycles (flash, copy files, reset, HTTP checks) without asking permission
  each time. Only ask the human for a physical action (RESET button press,
  re-plugging USB) and batch those requests.
- **Device URL: `http://192.168.5.56/`** (STA on home WiFi; DHCP — if it stops
  responding, re-check the boot log / COM ports, the IP may have moved).
  Use it directly instead of asking the user for the address each time.
- **Device password (auth token): `testtest`** — send as
  `Authorization: Bearer testtest` (or `X-Auth-Token: testtest`) on all
  `/api/*` and `/update` calls; the browser UI stores it in localStorage.

## Environment facts (verified, don't re-guess)

- Host is Windows, PowerShell. `python` = CPython 3.15. `pip` works.
- `esptool v5.6.0` and `mpremote 1.29.0` are installed (`python -m esptool`,
  `python -m mpremote`). `pyserial` + `esptool` were pip-installed during this
  session; `microdot` + `pytest` too (host-side only).
- Helper scripts live in `C:\Users\miguel\AppData\Local\Temp\opencode\`
  (`repl_check.py`, `soft_reset.py`, `stop_app.py`, `deploy_raw.py`, …).
  Reuse them instead of one-liners.
- Repo has host tests: `python -m pytest tests/ -q` (13 tests, hardware stubbed
  in `tests/stubs.py`). Run after every edit.

## Hardware: ports, buttons, hangs

- The board has TWO USB ports. USE THE SERIAL (UART) PORT as the primary:
  a WCH CH343 USB-serial bridge (`VID 1A86`/`PID 55D3`, seen as `COM11`)
  wired to the ESP32's UART0. MicroPython REPL works there, and it proved
  far more stable than native USB — a 60KB verified deploy plus reboot
  capture completed in one session with zero hangs. The OTHER (native USB)
  port enumerates as VID `303A` (PID `1001` ROM / `4001` MicroPython, was
  `COM9`/`COM10`) and repeatedly goes unresponsive after bursts of serial
  activity, needing a physical RESET each time. If a port goes silent,
  re-list with `[System.IO.Ports.SerialPort]::getPortNames()` and
  `Get-PnpDevice -Class Ports` — COM numbers move on re-enumeration.
- There is a physical RESET button. On the OLD (standard, memory-starved)
  firmware the board became unresponsive after bursts of serial activity and
  needed a reset press every time. With the SPIRAM_OCT firmware it has been
  stable: full flash + 26-file deploy + reboots with no hangs. Reach for the
  button only after re-checking the port list and the boot log — and consider
  that a hang may mean the wrong firmware variant got flashed again.
- `netsh wlan show networks` is UNRELIABLE for confirming the ESP AP:
  `ESP32-Agent-Setup` never appeared in scans even while the device serial log
  showed `active=True` with `192.168.4.1`. Trust the device log, not netsh.

## Flashing MicroPython

- **Running firmware: `ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin`
  (the SPIRAM_OCT variant — this is REQUIRED, see below).** Verified
  byte-identical to the official micropython.org download (SHA256
  `AB24EADF…1BD176`) before flashing. Local copies in the Temp dir. Official
  source: `https://micropython.org/download/ESP32_GENERIC_S3`, flash at offset
  `0` (`write-flash 0 …`), 460800 baud. `erase-flash` takes ~55s.
- **DO NOT go back to the standard build.** This board reports
  `Embedded PSRAM 8MB (AP_3v3)` from esptool — that is OCTAL PSRAM. The
  MicroPython download page states: "if your board has Octal SPIRAM, then use
  the spiram-oct variant." The standard build cannot drive octal PSRAM, so it
  silently falls back to internal RAM:
  - standard build: GC heap **0.2 MB**, largest contiguous block **22 KB**
  - SPIRAM_OCT build: GC heap **7.94 MB**, largest contiguous block **8.2 MB**

  The old note here claimed the standard build "is what booted and runs" — it
  boots, but every HTTPS request is a coin flip. That wrong note caused a long
  debugging session; it is corrected now.
- Symptoms of the wrong build (all were real): mbedTLS handshakes hang until
  the socket timeout (`ETIMEDOUT`), or fail fast with `OSError(1)`/`EPERM`.
  Serial shows `E (…) esp-aes: Failed to allocate memory`. **The 1st TLS
  handshake after boot often succeeds and later ones fail** — a very
  misleading pattern that looks like flaky networking but is buffer
  exhaustion. `ethernet/README`-style "upstream is slow" theories are wrong;
  the same request from the PC completes in 0.6s.
- Quick on-device check that the firmware is right:
  `import gc; gc.collect(); print(gc.mem_free())` → must be ~8 000 000, not
  ~90 000. Or `esp32.idf_heap_info(esp32.HEAP_DATA)` → must show a region with
  ~8 MB free and a ~8 MB largest block.
- Microdot is vendored on-device at `/lib/microdot/` (`__init__.py`,
  `microdot.py`, `multipart.py`, `helpers.py`, downloaded as raw files from
  `https://raw.githubusercontent.com/miguelgrinberg/microdot/main/src/microdot/`).
  `mpremote mip install github:…/microdot` DOES NOT WORK (tries to fetch
  `package.json`, fails). Don't retry mip; copy files. **`erase-flash` wipes
  these — remember to re-deploy `/lib` after any flash.**
- `erase-flash` also wipes `config.json` (WiFi creds, API key, auth token) and
  `chatlog.jsonl`. Back them up first — read them over the REPL as base64
  chunks (`binascii.b2a_base64`) and restore after.

## MicroPython platform limits (cost real bugs)

- **Only `utf-8`/`ascii` codecs exist.** `b.decode("iso-8859-1")` raises
  `unknown encoding: iso-8859-1`. This broke every successful LLM response in
  `llm._post_raw` while TLS was also failing, so it stayed hidden. Parse HTTP
  headers on **bytes** (`b"content-length:"`), never via a codec. Guarded by
  `tests/test_micropython_compat.py`.
- **SSL sockets have no `settimeout()`.** `ssl.wrap_socket(...)` returns an
  `SSLSocket`; calling `.settimeout()` on it raises
  `'SSLSocket' object has no attribute 'settimeout'`. Set the timeout on the
  plain socket *before* wrapping and guard any call afterwards
  (`tools/tool_web_fetch.py`, `llm.streamChat`).
- **NTP / clock epoch:** there is no NTP sync by default — the RTC boots at
  **2000-01-01** and mbedTLS will not handshake against it. `net.syncTime()`
  runs at boot right after `net.ensure_dns()` and prints `[ntp] time synced:
  (...)`. **MicroPython's `time.time()` counts from 2000-01-01, not 1970**, so
  the old guard `> 1700000000` could never trip before ~2053 (every soft boot
  re-ran NTP and printed `[ntp] sync failed: ETIMEDOUT` when the pool was
  slow). It now uses `_PLAUSIBLE_TIME = 757382400` (2024-01-01 since 2000). A
  missing `[ntp] time synced` line on a soft boot is normal — the RTC keeps
  the previous date, so the guard skips NTP. After a full power cycle, a
  missing line plus HTTPS failures means NTP did not sync.
- A ~40 KB file cannot be read whole into RAM on the wrong build
  (`MemoryError: allocating 31232 bytes`) — another quick wrong-firmware tell.


## mpremote

- **With the correct SPIRAM_OCT firmware, `mpremote` is reliable and fast.**
  All 26 app files + `/lib/microdot` deployed with correct sizes in one pass
  (one `mpremote connect COM11 cp <local> :<remote>` per file). The old
  "could not enter raw repl" flakiness was largely a symptom of the
  memory-starved standard build; re-test before assuming it's flaky again.
- Still do NOT chain commands in one invocation (`cp a :a cp b :b` misparses;
  `fs mkdir` eats following args). One operation per invocation.
- `mpremote exec` runs a multi-line snippet: useful for `os.mkdir`,
  `os.stat` size checks, and cleanup (`mpremote connect COM11 rm a b c`).
- Verify every copy: `mpremote connect PORT exec "import os;print(os.stat('x')[6])"`
  and compare to the local size. An echoed "cp ok" proves nothing.
- Fallback when mpremote won't connect but the port is enumerated: raw serial
  REPL. Read/deploy files as **base64 chunks** (`binascii.b2a_base64`,
  512-byte chunks) — raw `repr()` chunks get mangled by CRLF translation and
  silently truncate (one read returned 368 of 384 bytes every time). Always
  assert the final device `os.stat(...)[6]` equals the local size.

- Error detection on echoed output: match `"Traceback (most recent call last)"`
  EXACTLY. Never match bare `"Error"` — file contents (e.g. JS `new Error`)
  echo back and cause false failures (this exact bug cost a full deploy cycle:
  all-"ok" output with nothing written). Also treat EMPTY responses as failure,
  not success, and always assert the final SIZE equals the local file size.
- Entering REPL (Ctrl-C) KILLS the running app — `KeyboardInterrupt` inside
  `main.py`'s `asyncio.run`. That traceback is also your proof the app WAS
  running. Ctrl-D soft-resets back into the app. Never run REPL checks
  "just to look" on a healthy device; you'll take the server down and need
  another reset cycle.

## Boot / REPL timing

- After a (soft) reset the `=== Agent boot ===` banner prints within ~2s.
  `boot_listen.py` sleeps 4s first — too late, misses it. Listen IMMEDIATELY
  after triggering reset, or trigger reset from the same script.
- `soft_reset.py` (Ctrl-C, Ctrl-D, listen 25s) is the standard reboot-and-capture.
- `stop_app.py` (Ctrl-C, expect `IN-REPL`) is the standard "get a prompt".
- esptool can't talk to a MicroPython-running board (`No serial data received`
  is EXPECTED then — it only answers in ROM download mode). Don't mistake that
  for a dead board.

## Code-specific landmines

- `net.startAP`: for the OPEN setup network, OMIT the password arg and force
  `authmode=network.AUTH_OPEN`. Passing `password=""` yields a broken/hidden AP.
  (Fixed this session; `net.py` also prints `ap.ifconfig()` at boot now — keep it.)
- `www/agent.html` had `load();` INSIDE its own `load()` body (plus the real
  call at the bottom) → infinite self-refresh that wiped the Base URL field as
  you typed AND hammered `/api/api/agent`. One-line fix, deployed as
  `www/agent.html` SIZE 6223. NOTE: the bug text was byte-extracted from the
  C++ `web_ui.h`, so the original C++ firmware likely has it too. When porting
  or syncing UI files, grep for `load();}`-style self-recursion on every page.
- `server.py` SSE (`/api/chat-stream`) is **true upstream streaming now**
  (`llm.streamChat`): `stream:true` + HTTP/1.1 + incremental
  `Transfer-Encoding: chunked` decode (`llm._ChunkedReader`), re-emitted as
  `data: {"delta"}` events. Measured on-device: headers 0.16s, first token
  ~2.3s, 150 deltas spread over 4.7s for a 1.6 KB answer. The old
  "buffered, do not fix" note was a symptom of the 0.2 MB heap build —
  mbedTLS could not allocate buffers mid-stream, so the connection wedged.
  Event contract is unchanged (`delta`/`reasoning`/`need_tools`/DONE), and
  `need_tools` still makes `chat.html` fall back to `/api/chat` for the
  agentic tool loop (verified: `get_status` at 5.1s).
- **Chat memory:** the SSE path must call `agent_tools.appendChatLog` after a
  successful stream, or normal chat leaves `chatlog.jsonl` empty and the device
  forgets everything after a refresh (this was a real bug — the C++ original
  had it too). Do not log when `{"need_tools":true}` is sent: the browser's
  `/api/chat` fallback owns that turn. `chat.html` restores the transcript
  from `/api/memory?tail=20` and seeds its `history` array; its **Clear** button
  posts `{"clear_log":true}` to `/api/memory`, empties `history` and the view,
  and bumps `chatGen` so a pending restore cannot re-add old turns. Log
  injection is skipped whenever the browser sends history (`if not history`) so
  the same turns are not sent twice in the prompt.
- Streaming must use **HTTP/1.1**; HTTP/1.0 servers cannot send chunked
  bodies, so an SSE response would either be buffered or require closing the
  connection to signal the end. The buffered path (`_post_raw`) stays on
  HTTP/1.0 deliberately, where Content-Length is guaranteed.
- `llm.postLLM` uses a RAW SOCKET (`_post_raw`, HTTP/1.0, 45s timeouts), NOT
  urequests — urequests has no timeout on MicroPython, and a stalled upstream
  wedged the SSE generator forever (browser showed a forever-ticking cursor
  with no reply). Same class of fix as `/api/models` streaming. Live-tested
  against DeepInfra (401 without key) in `tests/test_llm_post.py`.
- `agent_tools.buildSystemPrompt()` wording matters a lot. The old prompt
  ("ESP32, low RAM. Be brief") + a `web_fetch` tool made the model answer
  "I don't have offline knowledge to share, but I can fetch that from the
  web" to "Tell me about Paris". Same model + neutral prompt answers it fully
  in 1.9 KB, so this was prompt-induced, not a model limit. Keep the explicit
  "you have full general knowledge, answer directly without a tool" clause,
  and do not re-add "low RAM" (the board has ~8 MB free now).
- `config.json`, `memory.txt`, `chatlog.jsonl` are gitignored device state.
  `/update` refuses them (plus `config.json.tmp`). Keep that blocklist.
- **No native dialogs app-wide:** `alert()`, `confirm()` and `prompt()` are
  banned in every `www/*.html` page — always use an in-page modal
  (see the promise-based modal in `www/files.html`, same pattern as the
  chat/functions clear-confirm modals). Grep for
  `\b(alert|confirm|prompt)\s*\(` must return zero matches.
- **Files Explorer (`/files`, `www/files.html` + `/api/files*` in `server.py`):**
  Windows-Explorer-style page — left Quick-access/sidebar, breadcrumb bar,
  Details table (Name/Type/Date modified/Size, sortable), search filter,
  New folder / Upload / Download / Rename / Delete, and an in-page editor
  with dependency-free syntax highlighting (Python/HTML/JS/CSS/JSON,
  textarea-over-highlighted-pre overlay, Ctrl+S saves). Uses the full browser
  width (no centred 800px column). Backend is pure `os.listdir`/`os.stat`
  helpers (`_fs_norm`, `_fs_list_dir`, `_fs_read_text`, …) so host tests cover
  them (`tests/test_files.py`, `_FS_ROOT` override). 100KB read / 200KB
  write caps; binary files are download-only. Download accepts the auth token
  as `?token=` because plain links cannot set headers.

## Deploy flow that works

1. Use the SERIAL port (`COM11` last seen — verify, it moves).
2. One `mpremote connect <PORT> cp <local> :<remote>` per file, then verify
   each with `os.stat(...)[6]` == local size. No sleeps needed now. Deploy
   `tools/` and `www/` into existing dirs; `os.mkdir` them first via
   `mpremote exec` if missing. Re-deploy `/lib/microdot` after any flash.
3. Soft-reset (`Ctrl-C` then `Ctrl-D`, or `mpremote reset`) → confirm the
   banner and `WiFi OK:`/`AP started:`. `[ntp] time synced:` only appears on a
   full power cycle — a soft reset keeps the RTC and skips NTP.
4. Verify behaviour over HTTP on the LAN, not via REPL — entering the REPL
   kills the server. `POST /api/chat` with
   `Authorization: Bearer <auth_token>` and `{"message":"hello"}` should
   return 200 with a real reply in ~2-4s. `/api/debug-raw?message=hi` is the
   no-tools path for isolating upstream problems from the agentic loop.

## Advice to the next agent

- Prefer reading/confirming over assuming: check COM ports, check file sizes
  on device (`os.stat`), check the boot log and `gc.mem_free()`. Every wrong
  assumption here cost a reset cycle; resets need the human's finger.
- When an HTTPS/LLM error appears, check the **firmware variant** and
  `gc.mem_free()` BEFORE theories about DNS, MTU, PoP routing or upstream
  latency. Test the upstream from the PC (`urllib`) to split device-vs-server
  in seconds — in this session the PC took 0.6s while the device timed out.
- Batch questions to the user (one reset press per answer). Never burn their
  patience on two consecutive physical actions — combine everything into what
  follows a single press.
- Keep responses short. Narrate state changes and next physical step only.
- The device is currently healthy on home WiFi `192.168.5.56` (STA), endpoint
  `https://api.deepinfra.com/v1/openai`, model
  `deepseek-ai/DeepSeek-V4.1-Flash-1017`, auth token enabled. Don't wipe
  `config.json`.

