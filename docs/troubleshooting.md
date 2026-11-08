# Troubleshooting & FAQ

## Board unreachable / IP changed

Re-check the serial boot log for the `WiFi OK:` line — DHCP may have moved
the IP. mDNS (`talaria-agent.local`) is best-effort only on MicroPython; use
the IP from the log.

## Setup network not visible

Trust the device serial log (`AP started: Talaria-Agent-Setup`), not the PC's
WiFi scan, which can miss it. Open `http://192.168.4.1/wifi` manually.

## Chat fails / TLS errors

The clock must be plausible for TLS: after a full power cycle confirm
`[ntp] time synced:` in the log. On the device run
`import gc; print(gc.mem_free())` — it must read ~8 000 000; ~90 000 means
the wrong (non-SPIRAM_OCT) firmware was flashed. See
[Build & Deployment](./build-and-deployment.md).

## Uploads fail verification

Re-run the deploy and compare sizes — only `os.stat(...)[6]` equality
counts. Prefer the UART port; COM numbers move on re-enumeration. See
[Build & Deployment](./build-and-deployment.md) and the
`--verify-only` mode of `scripts/esp_deploy.py`.

## REPL contact killed the server

Expected — entering the REPL stops the app. Reset the board (`--reset` flag
or RESET button) and verify over HTTP instead.

## First paint is slow / stalls

The app serialises API calls for the microcontroller's network stack;
`/api/models` can take ~6 s and is fetched lazily (on picker open, never at
page start). In the browser console, `window.__talariaNet` shows the last 40
calls with timings, and `window.__talaria` the live dashboard state.

## Forgot the device token

Clear it via serial/`mpremote` by editing `config.yaml`
(`security.auth_token`), or factory-reset from System (typed confirmation —
deletes config, memory, and sessions).
