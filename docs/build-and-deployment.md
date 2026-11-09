# Build & Deployment

How the firmware image, the Python app, and the dashboard get onto the board.
Target board: **ESP32-S3 N16R8** (16 MB flash, 8 MB octal PSRAM).

## 1. Flash MicroPython once (USB)

Required variant: **`ESP32_GENERIC_S3-SPIRAM_OCT`** (octal-PSRAM build from
`https://micropython.org/download/ESP32_GENERIC_S3`). The standard build
cannot drive octal PSRAM and leaves the board with ~0.2 MB heap instead of
~8 MB, which breaks every TLS connection.

```powershell
esptool --chip esp32s3 --port COM11 erase_flash
esptool --chip esp32s3 --port COM11 write_flash -z 0 ESP32_GENERIC_S3-SPIRAM_OCT-*.bin
```

- Flash at offset `0`, 460800 baud. `erase_flash` takes ~55 s.
- Use the **serial/UART port** (WCH CH343 bridge, e.g. `COM11`) — it is far
  more stable than the native-USB port for flashing and REPL work.
- Verify on-device: `import gc; gc.collect(); print(gc.mem_free())` must print
  ~8 000 000. (COM numbers move on re-enumeration — re-list ports if one goes
  silent.)
- `erase_flash` wipes everything, including `/lib/microdot`, `config.yaml`,
  and `/opt/data` — back up device state first and re-deploy afterwards.

## 2. Install Microdot once (on-device library)

`mip install github:…/microdot` does not work (it looks for `package.json`).
Copy the four files as raw downloads from
`https://raw.githubusercontent.com/miguelgrinberg/microdot/main/src/microdot/`
into `/lib/microdot/` on the device:

- `__init__.py`, `microdot.py`, `multipart.py`, `helpers.py`

```powershell
python -m mpremote connect COM11 cp microdot.py :/lib/microdot/microdot.py
# … repeat per file, then size-verify with:
python -m mpremote connect COM11 exec "import os;print(os.stat('/lib/microdot/microdot.py')[6])"
```

## 3. Deploy the app + dashboard

### Full deploy

```powershell
cd ui; npm install; npm run build; cd ..
powershell -File deploy.ps1 -Port COM11
```

`deploy.ps1` copies `app/` (including `app/tools/`) and the dashboard
bundle (`www/index.html`, `favicon.svg`, `assets/app.js(.gz)`,
`assets/app.css(.gz)`), size-verifying each (`os.stat(...)[6]` == local size),
then reboots and waits for `http://<device>/api/status`. Flags: `-Build`
(rebuild the UI first), `-SkipUI` (code only), `-Port`.

### Incremental deploy (day-to-day)

```powershell
python scripts/esp_deploy.py app/server.py app/llm.py app/tools/tool_web_fetch.py --reset
python scripts/esp_deploy.py --verify-only app/server.py app/llm.py
```

One invocation uploads N files (`LOCAL[:REMOTE]` specs) with a single batched
verify (`SUMMARY ok=X fail=Y`). `--raw` uses a single raw-serial session
(base64 chunks) instead of `mpremote` subprocesses; `--reset` reboots after the
batch (REPL contact stops the app, so a reset is required to serve again).

## 4. Confirm it works

1. Watch the serial log for the banner: `=== Agent boot ===`, then
   `WiFi OK: 192.168.x.x` (station) or `AP started: Talaria-Agent-Setup`
   (setup mode, portal at `http://192.168.4.1/setup`).
2. Open `http://<IP>/` and run Setup (WiFi + provider endpoint/key/model).
3. Health check (replace `<token>` if a device token is set):

```powershell
curl -H "Authorization: Bearer <token>" http://<IP>/api/status
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" `
  -d '{"message":"hello"}' http://<IP>/api/chat
```

Expect `200` with `free_heap` ≈ 8 000 000 and a real model reply in ~2–4 s.

## UI build details

- `ui/` is Vite + React 19 + TypeScript + Tailwind v4. `npm run build`
  (`tsc -b --noEmit && vite build && node scripts/postbuild.mjs ../www`)
  type-checks, bundles to **one JS chunk + one CSS file**, writes them into
  `../www/`, prebuilds the `.gz` twins (MicroPython cannot gzip at request
  time — the twins cut first paint from ~7 s to ~2 s), and stamps
  `index.html` with a cache-busted `?v=<hash>`.
- Serving: `app/server.py` serves exactly `index.html`, `favicon.svg`, and
  `assets/*` from `www/`, preferring `.gz` when the client accepts gzip; every
  other non-`/api` path falls through to the SPA shell via the catch-all
  `@app.get("/<path:path>")` registered **last** (`app/server.py:3689`) so it can
  never swallow an API route.
- Cable-free UI push: `POST /api/ui/asset?path=assets/app.js` (raw body,
  ≤900 KB, auth required). For a ~430 KB bundle, `mpremote cp` is the more
  reliable path.
- `POST /update` accepts code/page files (`.py/.html/.json/.txt/.mpy/.js/
  `.css/.svg/.md`; 900 KB cap for `.js`/`.css`, 200 KB otherwise), routes web
  files into `www/`/`www/assets/`, refuses device state (`config.yaml`,
  memory, sessions, cron, …), then reboots. MicroPython itself is only ever
  flashed over USB (step 1).

## Filesystem image releases

`.github/workflows/release-fs.yml` builds the prebuilt image the README's
Easy install points at:

- Pushes to `main` (and manual dispatches) build + verify the image and keep
  it as a workflow artifact — no release.
- Pushing a `v*` tag builds, verifies, and publishes
  `talaria-fs-<tag>.bin` + `.sha256` as a GitHub Release with install notes.
- The job rebuilds the dashboard (`npm ci` + `npm run build`), stages the
  exact tree `deploy.ps1` ships (`/main.py`, `/boot.py`, `/app/*`, `/www/*`,
  `/lib/microdot/*` — microdot fetched from the same raw URLs as the manual
  step; no `config.yaml`, no `/opt/data`), packs it with a from-source
  `mklittlefs` build (`-s 14680064 -b 4096 -p 256`), and checks every staged
  file against the image listing (`scripts/verify_fs_image.py`, pinned by
  `tests/test_verify_fs_image.py`).
- The image targets the MicroPython `vfs` partition: offset `0x200000`, size
  `0xE00000` (read from a live board via `esp32.Partition`; matches
  `/api/stats` `fs_total`). If MicroPython ever changes its S3 partition
  layout, these constants (`env.FS_SIZE`/`FS_OFFSET`) must move with it.
- Before cutting a release, `pytest tests/ -q` must be green — the image
  bakes in whatever is committed. To cut one: `git tag vX.Y.Z &&
  git push origin vX.Y.Z`, then watch the workflow run and sanity-check the
  published SHA256.
