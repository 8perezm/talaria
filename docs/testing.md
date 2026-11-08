# Testing

Host-side suite: no board required. Hardware is stubbed so every test runs on
plain CPython.

## Run

```powershell
pip install microdot pytest
python -m pytest tests/ -q
```

## Layout

- `tests/stubs.py` — `machine`, `network`, `esp32`, `urequests`, `uasyncio`
  stand-ins imported before the device modules.
- `tests/test_api_contract.py` — route/behaviour guarantees (reset vs reboot,
  backup redaction matrix, checkpoint pruning).
- `tests/test_spa.py` — sidebar ↔ route parity (`ui/src/components/Shell.tsx`
  `NAV` vs `ui/src/App.tsx` `<Route>`), house rules (no
  `alert`/`confirm`/`prompt`, no CDN, palette tokens, `cursor: pointer` on
  buttons), login-gate shape (`/login` exempt like `/setup`, `/wifi`,
  `/update`).
- `tests/test_config*.py`, `test_yamlish.py` — schema normalisation, YAML
  subset, form/raw save semantics, secret masking, legacy `config.json`
  migration.
- `tests/test_llm*.py`, `test_stream_chunked.py`, `test_models_stream.py` —
  raw-socket bridge, chunked SSE decode, catalogue fetch.
- `tests/test_files.py`, `test_mini_phase*.py`, `test_server_helpers.py` —
  `/opt/data` lock, system hatch, fs caps, route helpers.
- `tests/test_conversation_memory.py`, `test_session_delete.py`,
  `test_sessions_export.py` — session store, export truncation guards.
- `tests/test_cron_scripts.py`, `test_theme_*.py`, `test_login.py`,
  `test_deploy.py`/`test_esp_deploy.py`, `test_micropython_compat.py`, … —
  cron script sandbox rules, theme sync, login verifier, deploy pure helpers,
  codec/socket platform limits.

## Conventions

- Keep device-only imports behind the stubs; any new module that touches
  hardware must import cleanly under `tests/stubs.py` or be refactored so its
  pure logic is testable without the board.
- Pin every user-visible contract you change (redaction shapes, export
  formats, route lists, theme defaults) — the suite is the spec reviewers
  check first.
- On-device verification (after `pytest` is green): deploy with
  `python scripts/esp_deploy.py … --reset`, then exercise `POST /api/chat`
  and the SSE stream over HTTP; REPL checks stop the server, so prefer HTTP.
