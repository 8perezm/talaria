# config.py — persisted settings (WiFi, endpoint, model, tools mask) + helpers.
# MicroPython port of src/config.h/.cpp. Uses config.json instead of NVS
# Preferences so it works on any board and is easy to inspect via REPL.
try:
    import ujson as json
except ImportError:
    import json

try:
    import os
except ImportError:
    os = None

AP_SSID = "ESP32-Agent-Setup"
AP_PASS = ""  # open AP for easy onboarding
MDNS_NAME = "esp32-agent"
CONFIG_PATH = "config.json"

cfgSsid = ""
cfgPass = ""
cfgEndpoint = ""
cfgApiKey = ""
cfgModel = "gpt-4o-mini"
cfgAuthToken = ""

# tools mask is initialised after tools registry import to avoid circular import.
# Default: all-on (see agent_tools.all_tools_mask()).
gToolsMask = 0


def _read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return None


def _write_file(path, text):
    # atomic-ish: write tmp then rename (MicroPython os.rename exists)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)


def loadConfig():
    """Load settings from config.json into globals. Mirrors loadConfig()."""
    global cfgSsid, cfgPass, cfgEndpoint, cfgApiKey, cfgModel, cfgAuthToken, gToolsMask
    raw = _read_file(CONFIG_PATH)
    d = {}
    if raw:
        try:
            d = json.loads(raw) or {}
        except Exception:
            d = {}
    cfgSsid = d.get("wifi_ssid", "") or ""
    cfgPass = d.get("wifi_pass", "") or ""
    cfgEndpoint = d.get("api_endpoint", "") or ""
    cfgApiKey = d.get("api_key", "") or ""
    cfgModel = d.get("api_model", "") or "gpt-4o-mini"
    if not cfgModel:
        cfgModel = "gpt-4o-mini"
    cfgAuthToken = d.get("auth_token", "") or ""
    # tools mask: default all-on computed lazily by caller
    try:
        from agent_tools import all_tools_mask
        all_on = all_tools_mask()
    except Exception:
        all_on = 0x3FF
    m = d.get("tools_mask", all_on)
    try:
        m = int(m)
    except Exception:
        m = all_on
    if m == 0:
        m = all_on
    else:
        # auto-enable newly added tools when stored value equals an old "all on"
        try:
            from agent_tools import TOOL_COUNT
            for k in range(1, TOOL_COUNT):
                old_all = (1 << k) - 1 if k < 32 else 0xFFFFFFFF
                if m == old_all:
                    m = all_on
                    break
        except Exception:
            pass
    gToolsMask = m


def _save_patch(patch):
    d = {}
    raw = _read_file(CONFIG_PATH)
    if raw:
        try:
            d = json.loads(raw) or {}
        except Exception:
            d = {}
    d.update(patch)
    _write_file(CONFIG_PATH, json.dumps(d))


def saveToolsMask(m):
    global gToolsMask
    gToolsMask = int(m)
    _save_patch({"tools_mask": int(m)})


def saveAuthToken(token):
    global cfgAuthToken
    t = (token or "").strip()
    if len(t) > 128:
        t = t[:128]
    _save_patch({"auth_token": t})
    cfgAuthToken = t


def saveConfig(ssid, passwd, endpoint, key, model):
    global cfgSsid, cfgPass, cfgEndpoint, cfgApiKey, cfgModel
    m = (model or "").strip() or "gpt-4o-mini"
    _save_patch({
        "wifi_ssid": ssid or "",
        "wifi_pass": passwd or "",
        "api_endpoint": endpoint or "",
        "api_key": key or "",
        "api_model": m,
    })
    cfgSsid, cfgPass = ssid or "", passwd or ""
    cfgEndpoint, cfgApiKey = endpoint or "", key or ""
    cfgModel = m


def saveWifiOnly(ssid, passwd):
    global cfgSsid, cfgPass
    _save_patch({"wifi_ssid": ssid or "", "wifi_pass": passwd or ""})
    cfgSsid, cfgPass = ssid or "", passwd or ""


def saveAgentOnly(endpoint, key, model):
    global cfgEndpoint, cfgApiKey, cfgModel
    m = (model or "").strip() or "gpt-4o-mini"
    _save_patch({"api_endpoint": endpoint or "", "api_key": key or "", "api_model": m})
    cfgEndpoint, cfgApiKey = endpoint or "", key or ""
    cfgModel = m


def chatCompletionsUrl(base):
    u = (base or "").strip()
    while u.endswith("/"):
        u = u[:-1]
    if u.endswith("/chat/completions"):
        return u
    if u.endswith("/chat/completion"):
        return u + "s"
    return u + "/chat/completions"


def modelsUrl(base):
    u = (base or "").strip()
    while u.endswith("/"):
        u = u[:-1]
    suffix = "/chat/completions"
    if u.endswith(suffix):
        u = u[: -len(suffix)]
    return u + "/models"


def maskedKey(k):
    k = k or ""
    if len(k) <= 8:
        return "****"
    return k[:4] + "****" + k[-2:]
