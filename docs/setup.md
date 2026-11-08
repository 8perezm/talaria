# Setup & Configuration

First-run setup and everyday settings. For the setting registry, YAML parser
details, and config APIs, see [Configuration](./configuration.md).

## First run

1. Power the board. If no WiFi is configured yet, it starts the open
   `Talaria-Agent-Setup` network with a captive portal.
2. Join that network on your phone/laptop — most devices land on the setup
   page automatically; otherwise open `http://192.168.4.1/wifi`.
3. Press **Scan**, pick your home WiFi, enter the password, **Save & Reboot**.
4. Rejoin your home WiFi, then open `http://<IP>/` (IP from the serial
   `WiFi OK:` line) and finish **Setup**: provider endpoint, API key, model.

## Settings

All settings live in `config.yaml` at the device root. The easiest path is
the dashboard — **Setup** (first run), **Config** (provider, network, chat,
theme, security), **Keys** (device token) — or edit `config.yaml` directly in
the Files editor.

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
```

- **Provider:** endpoint base URL (`/chat/completions` is appended), API key,
  model id. An optional fallback provider is used only when the primary
  fails.
- **WiFi:** set SSID/password under Config → Network, then restart. Changing
  them from the setup page (`http://192.168.4.1/wifi`) needs no restart
  dance — just Save & Reboot.
- **Device token (optional, min 8 chars):** set it on the Keys page. The
  browser then logs in with username `admin` + the token, and API clients
  send `Authorization: Bearer <token>` (or `X-Auth-Token: <token>`).
- **Chat history:** how much of each message is kept (`entry_chars`), how
  many turns reload after a refresh (`restore_turns`), and the rolling-log
  budgets (`log_max_kb`, `log_keep_kb`).
- **Theme:** color scheme, fonts, and sizes under Config → Theme. Applies in
  the browser instantly, no restart.

## Upgrading

Upgrading from an older build: the first boot converts a legacy `config.json`
into `config.yaml` automatically (old file kept as `config.json.bak`).
Secrets stay masked in the dashboard until you press **Reveal**.
