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
  Reuse them instead of one-liners. For uploads prefer the repo CLI
  `scripts/esp_deploy.py` (multi-file copy + size verify in one invocation).
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
- `erase-flash` also wipes `config.yaml` (WiFi creds, API key, auth token),
  `config.json.bak`, every saved conversation (`opt/data/sessions/`) and the
  activity log. Back them up first — read them over
  the REPL as base64 chunks (`binascii.b2a_base64`) and restore after.

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
  (`app/tools/tool_web_fetch.py`, `llm.streamChat`).
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

- **Upload with `scripts/esp_deploy.py`, not bare `mpremote cp` loops.**
  One CLI invocation copies N files and verifies every one, so the agent
  spends one tool call per batch instead of one per file:
  `python scripts/esp_deploy.py app/server.py app/llm.py app/tools/tool_x.py --reset`.
  Specs are `LOCAL[:REMOTE]` (remote defaults to the repo-relative path);
  `--verify-only` compares device sizes to local without copying;
  `--raw` uses a single raw-serial session (base64 chunks) instead of
  mpremote subprocesses; `--reset` reboots after the batch. Pure mapping /
  parsing helpers are pinned by `tests/test_esp_deploy.py` (no hardware).
  Live-tested on the bench board in both modes (multi-file copy + verify,
  cross-backend verify agreement on a raw-uploaded file).
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
- **Cron script jobs (Hermes parity, 2026-11-08):** jobs have optional
  `script` (workspace `.py`, norm `opt/data/workspace/...`, shown as
  `/workspace/...` in Files) + `no_agent` bool. `no_agent=true` runs the
  script INSTEAD of the agent turn and delivers stdout verbatim (Hermes
  "no_agent: run the script only"); otherwise stdout is prepended to the
  agent prompt. Bare names map to the workspace root (`hello.py` →
  `workspace/hello.py`); `..` and `opt/...` outside the workspace are
  refused. Scripts exec with print-capture (8 KB source / 1 KB output caps,
  no exec_py import blocklist — same trust as Files writes). A job needs a
  prompt OR (no_agent + script). Jobs have an optional `name` display label
  (<=60 chars, Hermes parity). Covered by `tests/test_cron_scripts.py`.
- **Chat-created files live under `opt/data/workspace/`** (prompt + tool
  descriptions pin this; no code jail — flashing tests write at the repo
  root). Cron scripts must be there too (enforced in `cron._norm_script`).
- **Chat header button is "New Chat"** (not Clear) and shows no toast on
  success — `ui/src/pages/ChatPage.tsx`. Keep it that way.
- **Chat memory:** the SSE path must call `agent_tools.appendChatLog` after a
  successful stream, or normal chat leaves the session file empty and the device
  forgets everything after a refresh (this was a real bug — the C++ original
  had it too). Do not log when `{"need_tools":true}` is sent: the browser's
  `/api/chat` fallback owns that turn. `ChatPage.tsx` restores the transcript
  from `/api/memory` (no `?tail=`; the device picks the depth from Config) and
  seeds its `history` array. Log injection is skipped whenever the browser
  sends history (`if not history`) so the same turns are not sent twice.
  **Per-message retention is configurable:** `config.cfgChatEntryChars`
  (`chat.entry_chars` in config.yaml, Config → Chat), default 4000,
  clamped 500–20000. It bounds both `agent_tools.appendChatLog` (storage) and
  `server._read_log_tail` (restore). The old hard caps (1500 store / 800
  restore) silently cut a 6–7 paragraph reply down to ~2 paragraphs after a
  reload — don't reintroduce them. The LLM **prompt** caps in
  `injectRecentLog` / `llm.addHistoryCapped` (1500 chars) are separate on
  purpose. Changing the setting affects new messages only; entries already in
  a session keep the text they were stored with.
  **Rolling storage is config, not constants** (Config → Chat history):
  `chat_log_max_kb` (default 320, 64–4096), `chat_log_keep_kb` (default 200,
  32–max−32) and `chat_restore_turns` (default 20, 1–60). The old constants
  are just fallbacks (`LOG_MAX_BYTES`/`LOG_KEEP_BYTES` 320/200 KB, was 32/16).
  40 messages × 4000 chars ≈ 160 KB, so 20 multi-paragraph turns survive
  rotation. `/api/memory` returns `chat_restore_turns × 2` lines by default
  (explicit `?tail=` still works, capped 240).
  **Chunked I/O:** `fsutil.read_jsonl_tail` reads the file backwards in 16 KB
  blocks and parses only the lines it needs; `server._read_log_tail` and
  `agent_tools.injectRecentLog` both use it, and `_rotate_chatlog` copies the
  retained tail through a temp file in blocks, then swaps. RAM is one block +
  the requested entries, independent of log size. Measured on-device against a
  **1 MB** log: `tail=40` 1.72 s, `tail=4` 0.23 s (the old whole-file reader
  would pull the full megabyte). Do not replace the block readers with
  `f.read()` — that reintroduces the RAM/latency wall.
- **Sessions are conversations (2026-11-08, replaces the single-log model).**
  Storage is `opt/data/sessions/<id>.jsonl` — one file per conversation,
  append-only, plus `opt/data/sessions/active.json` (`{"id": ...}`) pointing at
  the web UI's current one. Web ids are `w<epoch>`; Telegram ids come from
  `sessions.session_id_for()` (flattened `mini_telegram_<chat>`), and Telegram
  resolves its file per turn so it can never hijack the web pointer.
  `GET /api/sessions` returns **conversations** (`{id,title,created,bytes,
  kind,active}`), `POST /api/sessions` starts one, `/api/sessions/activate`
  re-points the web UI, and `/api/sessions/delete` deletes a whole
  conversation (deleting the active one creates a fresh session). New Chat
  creates the id and points `active.json` at it; the file only appears on the
  first turn, so repeated presses cannot litter the store.
  **Old ids are refused, not reinterpreted:** `sessions.safe_id()` allows only
  `[a-z0-9_-]`, so the retired turn ids (`chatlog.jsonl:0:1:<hash>`) 400
  instead of addressing a file. `delete_turn`/`_drop_lines`/`_parse_turn_id`
  are gone with the old Session-page rows.
  **Migration:** `sessions.ensure_store()` (called from `initAgentFS` and every
  store reader) renames a legacy `chatlog.jsonl`/`chatlog.prev.jsonl` into two
  session files by mtime and makes the newer one active. Nothing is deleted.
  **`agent_tools.LOG_PATH` is no longer "the chat log".** It stays the legacy
  default; `agent_tools.active_log_path()` resolves
  `opt/data/sessions/<active>` on every call (never cache it in a global — a
  cached path survives a remount and writes to the wrong conversation).
  `appendChatLog`/`injectRecentLog`/`llm.callLLMWithTools`/`agent_core.runTurn`
  accept `log_path=`, which is how a turn is pinned to one session.
  **Cron is not a conversation.** `agent_tools.appendActivity()` writes
  `opt/data/activity.jsonl` (own 128/64 KB budget) and `cron._default_run`
  passes `log_path=ACTIVITY_PATH`, so job output is neither listed on
  /sessions nor injected as fake user/assistant history into the next chat
  turn. Before this split the last-8 log lines fed cron output back into the
  user's prompt.
  `/api/sessions` stays separate from `/api/trajectory` on purpose — the
  ShareGPT export keeps its exact shape and its tests pin it. `/api/memory`
  takes `?session=<id>` (and `?activate=1`), returns `session`, and exports
  `chatlog_tail` in `/api/backup` from the active conversation.
  `/api/reset` wipes every session file plus the activity log.
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
- `config.yaml`, `config.json`, `config.json.bak`, `memory.txt`, `cron.json`,
  `opt/data/sessions/` and `opt/data/activity.jsonl` are gitignored device
  state. `/update` refuses them (plus `config.yaml.tmp`).
  Keep that blocklist. The first boot after an upgrade migrates `config.json`
  into `config.yaml` and renames the old file to `config.json.bak`.
- **No native dialogs app-wide:** `alert()`, `confirm()` and `prompt()` are
  banned in every `www/*.html` page — always use an in-page modal
  (see the promise-based modal in `www/files.html`, same pattern as the
  chat/functions clear-confirm modals). Grep for
  `\b(alert|confirm|prompt)\s*\(` must return zero matches.
- **Files (`/files`, `ui/src/pages/FilesPage.tsx` + `/api/files*`):** the main
  area is a 1:1 port of upstream Hermes' `web/src/pages/FilesPage.tsx`, not the
  old Windows-Explorer layout. Header = "Files" + outlined path badge + refresh
  icon; body = mono path, outlined UPLOAD/CREATE, a dashed drop-zone button
  ("DROP FILES HERE" / path / "CHOOSE FILES"), then one bordered table with a
  fixed `minmax(12rem,1fr) / 7rem / 10rem / 5.5rem` grid for
  Name/Size/Modified/Actions, a ".." parent row, yellow folder icons, mono
  names, absolute `Intl.DateTimeFormat` timestamps, and ghost Open/Download +
  Trash actions. No stat strip, breadcrumb, search box or rename — adding those
  back breaks parity with the reference page.
  Deliberate deviation requested for usability: folders always group above
  files, and the Name/Size/Modified headers are sortable (click toggles
  asc/desc, arrow shows the active column; default = folders first, then name
  ascending). Sorting is client-side over the listed entries.
  Micro-only affordance kept: clicking a **file name** opens the full-screen
  editor (Ctrl+S saves) instead of downloading; the Download icon downloads.
  The editor opens in View mode with offline syntax highlighting
  (`ui/src/lib/highlight.ts`, zero deps — a highlight.js bundle was rejected
  as too heavy for the flash budget and unneeded since a CDN is banned
  offline) and an Edit tab switches to the plain textarea. The editor is
  portaled to `<body>` — without that the shell's `z-[2]`
  stacking context paints the sidebar over it. `Modal` is portaled for the same
  reason (its backdrop must dim the sidebar too).
  Backend is pure `os.ilistdir`/`os.stat` helpers (`_fs_norm`,
  `_fs_list_dir`, `_fs_read_text`, …) covered by `tests/test_files.py`
  (`_FS_ROOT` override). 100KB read / 200KB write caps; binary files are
  download-only. Download accepts the auth token as `?token=` because plain
  links cannot set headers. Uploads are text-read client-side and written via
  `/api/files/save` (the multipart `/api/files/upload` endpoint also exists).
- **Data home (`/opt/data`, Hermes parity):** `/api/files` is LOCKED to the
  user-data home — `/` lists `/opt/data`, every path maps under it, system
  code at flash `/` is unreachable through Files by construction (same idea
  as Hermes' `locked_root` on `/opt/data`). User state lives here:
  `memory.txt`, `user.txt`, `sessions/` (one file per conversation),
  `activity.jsonl` (`+.prev`), `cron.json`,
  `tg.json`, `bundles.json`, `pending_mem.json`, `skills/`,
  `pending_skills/`, plus `workspace/` (pre-created empty, reserved for later
  agent work). First boot after upgrade migrates pre-split root files into
  `/opt/data` (`fsutil.ensure_data_tree`, called from
  `agent_tools.initAgentFS`; best-effort, never raises) and the legacy
  single log into `sessions/` (`sessions.ensure_store`). Writes under
  `opt/data/sessions/` are refused by the file tools — conversations are
  append-only and owned by the store. `config.yaml` stays
  at `/` and is owned by the Config page, not Files. The agent's
  `read_file`/`write_file`/`search_files` keep full-flash access (refusals
  updated for the new prefixes); only the human browser is scoped.
- **System hatch (`/api/system/files*`):** full-flash list/read/download/save/
  mkdir/delete/rename with the same auth, caps and `.bak` checkpoints as
  Files, but a separate route + UI surface so a normal Files click can never
  brick the device. `config.yaml` edits validate + reload here (moved from
  `/api/files/save`); the Config page remains the primary editor. Delete
  refuses `opt` and `opt/data` (use `/api/reset`). Pinned by the lock/hatch
  tests in `tests/test_mini_phase7.py`.
- **Login gate:** full-screen `/login` route (Hermes-style, Talaria palette),
  fixed username `admin`, password = `security.auth_token`. `POST /api/login`
  is a stateless verifier over the existing Bearer mechanism (no
  cookies/sessions on the MCU — the browser keeps the token in `esp32_token`
  localStorage). Locked devices redirect to `/login`; `/setup`, `/wifi`,
  `/update` never redirect. Scoped API keys later slot into `unlock()` and
  the Bearer check without reworking this. Pinned by `tests/test_login.py`
  and `test_login_gate_shape` in `tests/test_spa.py` (`/login` is a utility
  route, exempt from nav parity like `/setup`).

## Deploy flow that works

1. Use the SERIAL port (`COM11` last seen — verify, it moves; the CLI
   auto-detects the CH343 bridge, `--port` overrides).
2. Batch the upload in ONE invocation (the CLI loops internally — mpremote
   misparses chained `cp a :a cp b :b`, so one operation per *mpremote*
   call, but many files per *CLI* call):
   `python scripts/esp_deploy.py <files...> --reset`. Parent dirs are
   created automatically; every file is size-verified (`os.stat(...)[6]`
   == local size) with a single batched stat, and `SUMMARY ok=X fail=Y`
   reports the batch. An echoed "cp ok" proves nothing — only SIZE
   equality passes. No sleeps needed now. Re-deploy `/lib/microdot` after
   any flash. `deploy.ps1` remains the full-deploy path (all code + UI +
   reboot + HTTP wait); the CLI is the incremental path.
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
  `config.yaml`.

## Dashboard: React SPA (2026-11-07, replaces the hand-written HTML pages)

- **The UI is React.** `ui/` is a Vite + React 19 + TypeScript + Tailwind v4
  project modelled on Nous Research's Hermes Agent dashboard. `npm run build`
  emits straight into `www/`:
      www/index.html            shell, cache-busted `?v=<hash>`
      www/assets/app.js         ONE chunk, ~442 KB
      www/assets/app.css        ~46 KB
      www/assets/app.js.gz      prebuilt gzip twin, ~130 KB
      www/assets/app.css.gz
  MicroPython cannot gzip at request time, so the twins are built on the host.
  Serving them cut first paint from ~7 s to ~2 s; `app.js` alone over plain
  flash is ~7 s. Do not delete the `.gz` files.
- **No per-route HTML files exist any more.** `server.py` serves the shell for
  every non-`/api` path via a **catch-all registered LAST** (`@app.get(
  "/<path:path>")`). If you move it earlier it swallows every `/api` route and
  the whole app 404s — that exact bug cost a debug cycle.
- **Design tokens are the Hermes LENS_0 palette**, ported into
  `ui/src/index.css` from upstream `web/src/index.css`: canvas `#041c1c`,
  cream midground `#ffe6cb`, square corners (`--radius: 0px`), hairline
  `current/15–20%` rules, uppercase micro-labels at `0.12em` tracking,
  nav items `13px` uppercase in a `240px` sidebar, active item = cream text +
  1 px left cream bar. Cream-filled "active" tabs invert to dark text.
  Custom DS fonts (Collapse/Rules/Mondwest) are **not** bundled — offline
  device, and they are not ours to redistribute. `system-ui` at the same
  weights/tracking reads nearly identically.
- **Nav ↔ route parity is a test, not a convention.** `tests/test_spa.py`
  parses `NAV` in `ui/src/components/Shell.tsx` and the `<Route>` list in
  `ui/src/App.tsx` and asserts they match both ways. Utility screens
  (`/setup`, `/wifi`, `/update`) are exempt — they are linked from the pages
  that own them.
- **House rules pinned by tests:** no `alert`/`confirm`/`prompt` anywhere (use
  the promise-based `useConfirm` modal), no CDN (single carve-out:
  `ui/src/lib/theme.ts` fetches user-selected Google Fonts on demand for
  Config → Theme; everything else must stay dependency-free),
  Talaria palette defaults unchanged in `index.css`, `esp32_token`
  localStorage key preserved so an already-unlocked browser stays unlocked
  across the upgrade.
- **Client request gate: `MAX_CONCURRENT = 1`** in `ui/src/lib/api.ts`. The
  ESP32's lwIP drops extra SYNs when several fresh connections arrive at
  once; TCP then retransmits on a 1/2/4 s backoff, which looked like an 8 s
  hang on first paint. Serialising all API calls turned startup into ~1.5 s of
  predictable round trips. **Do not raise this without measuring.**
- `/api/models` reaches the provider over TLS from the device and can take
  6 s — fetch it lazily (on picker open), never at page start, or it blocks
  the gate for everything else.
- **`fsutil.list_dir` does ONE stat per entry.** `os.ilistdir` already gives
  type and size; the old three-stats-per-entry version made a 33-entry root
  listing take 8.8 s. Now ~2.2 s. Keep it at one.
- Field debugging: `window.__talaria` holds live dashboard state,
  `window.__talariaNet` the last 40 API calls with timings. Both are cheap and
  worth keeping — they are the only console the device has.
- Upload path: `POST /api/ui/asset?path=assets/app.js` writes a bundle file
  (≤900 KB, only `index.html`/`favicon.svg`/`assets/*`). It failed for a
  ~430 KB body over `Invoke-WebRequest` in testing; `mpremote cp` is the
  reliable path for a full bundle (~77 s for `app.js`).
- `POST /update` accepts `.py/.html/.json/.txt/.mpy/.js/.css/.svg/.md`
  (900 KB cap for `.js`/`.css`, 200 KB otherwise) and routes web files into
  `www/` / `www/assets/`.
- Retired: `www/dash.css`, `www/icons.svg`, all `www/*.html` pages, and the
  tests that pinned them (`test_dash0/2/4/5/6/7a/7b`, `test_model_picker`,
  plus page-only cases in `test_dash3`, `test_console`, `test_stats`,
  `test_mini_phase9`, `test_conversation_memory`). The API-level guarantees
  that lived in `test_dash5` (reset vs reboot, backup redaction, checkpoint
  pruning) moved to `tests/test_api_contract.py`.
- **`/api/reset` IS FACTORY-WIPE + reboot** (deletes `config.yaml`,
  `config.json`, `config.json.bak`, memory and chat log), NOT a restart.
  **`POST /api/reboot` is the safe soft reset** (wipes nothing). No dashboard
  button wires to `/api/reset` except the typed confirmation on System —
  keep it that way.
- Backup redaction rule: `GET /api/backup` must NEVER emit raw
  `api_key`/`wifi_pass`/`auth_token`/`bot_token` (masked shapes only, gateway
  presence-only). Pinned by redaction-matrix test. No restore v1 — restore =
  /files editor + reboot.
- Flash: bundle totals ~490 KB on disk, ~630 KB with the `.gz` twins.

## Config: schema-driven page + YAML storage (2026-11-08)

- **`config.yaml` is the source of truth.** Nested sections: `agent`,
  `fallback`, `network`, `chat`, `security`, plus `tools.mask`. `config.json`
  is only read once for migration and renamed `config.json.bak`.
- **`config_schema.py` is the single registry** for field key, category,
  group, type, label, description, default, min/max and `restart`. Add a
  setting there and read it in `config.py`; the Config page renders it
  automatically (no per-setting React code).
- **`yamlish.py` is a deliberately small YAML subset** — maps, block/inline
  lists, inline maps, quoted strings, comments, bool/int/float/null. It
  rejects anchors, tags and block scalars. `yamlish.dumps(doc, order)` takes
  a dotted-path order map because MicroPython dicts are unordered;
  `config.dump_doc` supplies schema order.
- **APIs:** `GET /api/config/form` (fields + values; secrets blank + masked),
  `POST /api/config/form` `{values: {"dotted.key": value}}`,
  `GET /api/config/yaml` (redacted; `?secrets=1` reveals), and
  `POST /api/config/yaml` `{yaml}` (full replacement). Masked `****`
  placeholders are replaced with live secrets before saving; raw text is
  written back verbatim when it normalizes unchanged, so hand-written YAML
  comments survive a raw save.
- **Restart semantics:** form saves never reboot. Network fields return
  `restart_required: true` and the Network section shows a Restart button.
  Raw YAML changes to `auth_token` return the new token so the SPA updates
  `localStorage`.
- **Old flat endpoints still work:** `/api/config`, `/api/agent`, `/api/wifi`
  write through `config._save_patch` into the nested YAML.
- **Secrets stay masked by default.** The redacted YAML view is generated
  from the real file so unknown/hand-added keys are preserved. Do not make
  the default `/api/config/yaml` response return raw secrets.
- `memory.approval_enabled()` and `skillstore.approval_enabled()` now call
  `config.get_approval()`; do not reintroduce direct `config.json` reads.
- `main.py` restarts the Microdot server loop if it returns, so a wedged
  handler becomes a 2s restart instead of a silent drop to the REPL.

## Theme fonts: three roles, one source, applied before first paint (2026-11-08)

- **Defaults are graphite + Poppins (headers) / Space Grotesk (body) /
  JetBrains Mono (terminal)** — in `config_schema.py` FIELDS, `config.py`
  `DEFAULT_THEME_*`, `ui/src/lib/theme.ts` `THEME_DEFAULTS` and the baked-in
  `index.css` `:root` tokens (keep all four in sync; `test_theme_config` and
  `test_design_tokens_are_the_talaria_palette` pin them).

- **Exactly three type roles**, all from `config.yaml` via CSS custom
  properties set on `<html>` by `ui/src/lib/theme.ts`:
  `theme.font_headers` → `--theme-font-display` (page titles, `.panel-head`,
  `.label-display`, `.field-label`, `.chip`, `.table th`, `.md h1-3`),
  `theme.font_body` → `--theme-font-sans` (html/body/paragraphs/chat/buttons/
  inputs), `theme.font_mono` → `--theme-font-mono` (`code`, `pre`, `.font-mono-ui`,
  logs, the file editor). `theme.font_body_size` sets the root font-size, so
  every rem utility scales with it.
- **No component may hard-code a family.** `index.css` only ever writes
  `var(--theme-font-*)` (plus `inherit` for `.code-view code`), and the only
  inline `fontFamily` allowed is `fontStack(...)` in `ThemeSection.tsx`, which
  exists to *preview* a font before it is saved. `tests/test_theme_fonts.py`
  audits all of `ui/src` for violations — it caught panel titles, chips,
  field labels, table heads and markdown headings still using the body stack,
  so setting a Headers font used to change almost nothing.
- **First paint matters.** `applyTheme()` runs after a `/api/config/form`
  round trip (0.5–1.5 s behind the client gate), so before 2026-11-08 every
  page painted in the stock stack and visibly swapped afterwards — the likely
  origin of "the chat doesn't use my font". Now `applyTheme` caches the values
  in `localStorage['talaria_theme']` and `main.tsx` calls `applyBootTheme()`
  **before** `createRoot().render()`, so the first frame is already themed;
  `ThemeApplier` then reconciles with the device. Unsaved Config previews pass
  `{cache: false}` and never become the boot theme.
- **Locked views keep the look.** The `/login` gate cannot read the config
  (API is auth-gated), so it applies the cached theme instead of resetting to
  defaults; only a browser that has never seen a theme falls back to stock.

## Sessions page: ordering + one export per conversation (2026-11-08)

- The list has two ordering controls (`BY DATE` / `SIZE`) in the Conversations
  panel header, left of the stored-count chip; client-side over the fetched
  page. Clicking the active one flips asc/desc. Default = date descending
  (newest first), matching `sessions.list_sessions()`.
- **Export is a row action**, one button next to Delete. The old page-level
  Export only dumped the *active* conversation's `/api/memory` tail, so it is
  gone. Each row downloads
  `GET /api/sessions/export?id=<sid>&token=<auth>` — a plain `<a>` download
  (hence `?token=`, same pattern as `/api/files/download`) that returns
  `text/plain` + `Content-Disposition: attachment; filename="talaria-<sid>.txt"`.
- The sidebar bottom row is `theme` (left, deep-links to Config → Theme via
  `/config?section=theme`, consumed + cleared by `ConfigPage`) next to
  `Restart` (right-aligned text + icon).
- **Clickable = hand cursor.** Tailwind v4's preflight resets buttons to the
  arrow, so `index.css` base layer sets `button:not(:disabled) { cursor:
  pointer }` once instead of per-file classes. `test_spa.py` pins the rule
  and restricts `cursor-default` to full-screen modal backdrops.
- `sessions.export_text()` reads the file line by line with `_parse_line_full`
  (no `TRAJ_VALUE_CAP` truncation — the trajectory export caps at 1500 chars,
  a downloaded transcript must not) and stops at `EXPORT_MAX_CHARS` (400 KB)
  so a huge log cannot allocate the whole file twice. Pinned by
  `tests/test_sessions_export.py`.


