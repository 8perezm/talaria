# config.py — persisted settings in a hand-editable YAML file.
#
# The on-device file is config.yaml. It is intentionally plain block-style
# YAML (see yamlish.py) so a human can edit it over the Files editor, a REPL
# or `mpremote cp`. Older firmware wrote config.json; loadConfig() migrates it
# once and keeps config.json.bak as a safety copy.
#
# The shape is schema-driven (config_schema.py):
#
#   agent:      endpoint / model / api_key / max_iters
#   fallback:   endpoint / model / api_key
#   network:    wifi_ssid / wifi_pass / mdns_name / ap_ssid
#   chat:       entry_chars / restore_turns / log_max_kb / log_keep_kb
#   theme:      color_scheme / font_headers(+_size) / font_body(+_size) /
#               font_mono(+_size) — dashboard look, browser-applied, no restart
#   security:   auth_token / memory_write_approval / skills_write_approval
#   tools:      mask
#
try:
    import ujson as json
except ImportError:
    import json

try:
    import os
except ImportError:
    os = None

import config_schema as schema
import yamlish

AP_SSID = "Talaria-Agent-Setup"
AP_PASS = ""  # open AP for easy onboarding
MDNS_NAME = "talaria-agent"
CONFIG_PATH = "config.yaml"
LEGACY_CONFIG_PATH = "config.json"
LEGACY_BACKUP_PATH = "config.json.bak"
CONFIG_VERSION = 1

cfgSsid = ""
cfgPass = ""
cfgEndpoint = ""
cfgApiKey = ""
cfgModel = "gpt-4o-mini"
cfgAuthToken = ""
cfgFallbackEndpoint = ""
cfgFallbackKey = ""
cfgFallbackModel = ""
cfgMdnsName = MDNS_NAME
cfgApSsid = AP_SSID
agent_max_iters = 3
# Characters of each chat message kept in chatlog.jsonl and restored after a
# page reload. 4000 covers a full 800-token reply (~6-7 paragraphs); the old
# hard caps of 1500 (store) / 800 (restore) cut long answers in half.
DEFAULT_CHAT_ENTRY_CHARS = 4000
CHAT_ENTRY_CHARS_MIN = 500
CHAT_ENTRY_CHARS_MAX = 20000
cfgChatEntryChars = DEFAULT_CHAT_ENTRY_CHARS
# Rolling chat-log storage (Config -> Chat). Rotation rewrites only the newest
# slice, in fixed-size blocks, so RAM use stays flat as the log grows.
DEFAULT_CHAT_LOG_MAX_KB = 320
DEFAULT_CHAT_LOG_KEEP_KB = 200
CHAT_LOG_MAX_KB_MIN = 64
CHAT_LOG_MAX_KB_MAX = 4096
CHAT_LOG_KEEP_KB_MIN = 32
DEFAULT_CHAT_RESTORE_TURNS = 20
CHAT_RESTORE_TURNS_MIN = 1
CHAT_RESTORE_TURNS_MAX = 60
cfgChatLogMaxKB = DEFAULT_CHAT_LOG_MAX_KB
cfgChatLogKeepKB = DEFAULT_CHAT_LOG_KEEP_KB
cfgChatRestoreTurns = DEFAULT_CHAT_RESTORE_TURNS

# Dashboard theme (Config -> Theme). All browser-applied, no restart.
# Defaults are the graphite scheme plus the Google fonts above; size vars
# only take effect when changed.
DEFAULT_THEME_SCHEME = "graphite"
DEFAULT_THEME_FONT_HEADERS = "Poppins"
DEFAULT_THEME_FONT_BODY = "Space Grotesk"
DEFAULT_THEME_FONT_MONO = "JetBrains Mono"
DEFAULT_THEME_HEADERS_SIZE = 15
THEME_HEADERS_SIZE_MIN = 10
THEME_HEADERS_SIZE_MAX = 32
DEFAULT_THEME_BODY_SIZE = 15
THEME_BODY_SIZE_MIN = 10
THEME_BODY_SIZE_MAX = 24
DEFAULT_THEME_MONO_SIZE = 13
THEME_MONO_SIZE_MIN = 10
THEME_MONO_SIZE_MAX = 24
cfgThemeScheme = DEFAULT_THEME_SCHEME
cfgThemeFontHeaders = DEFAULT_THEME_FONT_HEADERS
cfgThemeHeadersSize = DEFAULT_THEME_HEADERS_SIZE
cfgThemeFontBody = DEFAULT_THEME_FONT_BODY
cfgThemeBodySize = DEFAULT_THEME_BODY_SIZE
cfgThemeFontMono = DEFAULT_THEME_FONT_MONO
cfgThemeMonoSize = DEFAULT_THEME_MONO_SIZE

# tools mask is initialised after tools registry import to avoid circular import.
# Default: all-on (see agent_tools.all_tools_mask()).
gToolsMask = 0


# ---------------------------------------------------------------------------
# low-level file helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# value clamps (shared with the REST API and the old flat save helpers)
# ---------------------------------------------------------------------------

def _clamp_iters(v, default=3):
    try:
        n = int(v)
    except Exception:
        return default
    if n < 1:
        return 1
    if n > 5:
        return 5
    return n


def _clamp_chat_entry_chars(v, default=DEFAULT_CHAT_ENTRY_CHARS):
    try:
        n = int(v)
    except Exception:
        return default
    if n < CHAT_ENTRY_CHARS_MIN:
        return CHAT_ENTRY_CHARS_MIN
    if n > CHAT_ENTRY_CHARS_MAX:
        return CHAT_ENTRY_CHARS_MAX
    return n


def _clamp_chat_log_max_kb(v, default=DEFAULT_CHAT_LOG_MAX_KB):
    try:
        n = int(v)
    except Exception:
        return default
    if n < CHAT_LOG_MAX_KB_MIN:
        return CHAT_LOG_MAX_KB_MIN
    if n > CHAT_LOG_MAX_KB_MAX:
        return CHAT_LOG_MAX_KB_MAX
    return n


def _clamp_chat_log_keep_kb(v, max_kb, default=DEFAULT_CHAT_LOG_KEEP_KB):
    # Leave at least 32 KB of headroom below the rotation trigger so every
    # rotation actually frees space instead of rewriting the same bytes.
    floor = CHAT_LOG_KEEP_KB_MIN
    ceiling = max_kb - 32
    if ceiling < floor:
        ceiling = floor
    try:
        n = int(v)
    except Exception:
        n = default
    if n < floor:
        return floor
    if n > ceiling:
        return ceiling
    return n


def _clamp_chat_restore_turns(v, default=DEFAULT_CHAT_RESTORE_TURNS):
    try:
        n = int(v)
    except Exception:
        return default
    if n < CHAT_RESTORE_TURNS_MIN:
        return CHAT_RESTORE_TURNS_MIN
    if n > CHAT_RESTORE_TURNS_MAX:
        return CHAT_RESTORE_TURNS_MAX
    return n


def _theme_scheme(v, default=DEFAULT_THEME_SCHEME):
    try:
        text = str(v).strip()
    except Exception:
        return default
    if text in schema.THEME_SCHEME_IDS:
        return text
    return default


def _theme_font(v, options, default="System Default"):
    try:
        text = str(v).strip()
    except Exception:
        return default
    if text in options:
        return text
    return default


def _clamp_theme_size(v, lo, hi, default):
    try:
        n = int(v)
    except Exception:
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _text(value, default=""):
    if value is None:
        return default
    text = str(value)
    return text if text != "" else default


def _mdns_name(value):
    text = _text(value, MDNS_NAME).strip()
    if not text:
        text = MDNS_NAME
    if len(text) > 32:
        text = text[:32]
    return text


def _ap_ssid(value):
    text = _text(value, AP_SSID).strip()
    if not text:
        text = AP_SSID
    if len(text) > 32:
        text = text[:32]
    return text


# ---------------------------------------------------------------------------
# document readers / writers
# ---------------------------------------------------------------------------

def _doc_from_legacy(d):
    """Convert the old flat config.json shape into the nested YAML shape."""
    doc = {"_config_version": CONFIG_VERSION}
    for flat in schema.FLAT_TO_PATH:
        path = schema.FLAT_TO_PATH[flat]
        value = None
        found = False
        if "." in flat:
            section, key = flat.split(".", 1)
            sec = d.get(section)
            if isinstance(sec, dict) and key in sec:
                value = sec[key]
                found = True
        if not found and flat in d:
            value = d[flat]
            found = True
        if found:
            schema.set_path(doc, path, value)
    for key in d:
        if key in schema.FLAT_TO_PATH:
            continue
        if key == "memory" or key == "skills":
            sec = d.get(key)
            if isinstance(sec, dict):
                rest = {}
                for sub in sec:
                    if sub != "write_approval":
                        rest[sub] = sec[sub]
                if rest:
                    doc[key] = rest
            continue
        if ((key in schema.CATEGORY_ORDER or key == "tools")
                and isinstance(d.get(key), dict)):
            sec = doc.get(key)
            if not isinstance(sec, dict):
                sec = {}
                doc[key] = sec
            for sub in d[key]:
                sec[sub] = d[key][sub]
            continue
        doc[key] = d[key]
    return doc


def _read_with_source():
    """Return (doc, source). Source is 'yaml', 'json' or ''."""
    raw_yaml = _read_file(CONFIG_PATH)
    if raw_yaml is not None:
        try:
            doc = yamlish.loads(raw_yaml)
            if isinstance(doc, dict):
                return doc, "yaml"
            print("[config] YAML root is not a mapping; trying legacy JSON")
        except Exception as e:
            print("[config] YAML parse failed:", str(e)[:120])
    for path in (LEGACY_CONFIG_PATH, LEGACY_BACKUP_PATH):
        raw = _read_file(path)
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if isinstance(d, dict):
            return _doc_from_legacy(d), "json"
    return {}, ""


def read_doc():
    """Read config.yaml (or migrate a legacy config.json) without changing globals."""
    return _read_with_source()[0]


def _value_for_key(key):
    if key == "agent.endpoint":
        return cfgEndpoint
    if key == "agent.model":
        return cfgModel
    if key == "agent.api_key":
        return cfgApiKey
    if key == "agent.max_iters":
        return agent_max_iters
    if key == "fallback.endpoint":
        return cfgFallbackEndpoint
    if key == "fallback.model":
        return cfgFallbackModel
    if key == "fallback.api_key":
        return cfgFallbackKey
    if key == "network.wifi_ssid":
        return cfgSsid
    if key == "network.wifi_pass":
        return cfgPass
    if key == "network.mdns_name":
        return cfgMdnsName
    if key == "network.ap_ssid":
        return cfgApSsid
    if key == "chat.entry_chars":
        return cfgChatEntryChars
    if key == "chat.restore_turns":
        return cfgChatRestoreTurns
    if key == "chat.log_max_kb":
        return cfgChatLogMaxKB
    if key == "chat.log_keep_kb":
        return cfgChatLogKeepKB
    if key == "theme.color_scheme":
        return cfgThemeScheme
    if key == "theme.font_headers":
        return cfgThemeFontHeaders
    if key == "theme.font_headers_size":
        return cfgThemeHeadersSize
    if key == "theme.font_body":
        return cfgThemeFontBody
    if key == "theme.font_body_size":
        return cfgThemeBodySize
    if key == "theme.font_mono":
        return cfgThemeFontMono
    if key == "theme.font_mono_size":
        return cfgThemeMonoSize
    if key == "security.auth_token":
        return cfgAuthToken
    return None


def _legacy_approval(doc, name, default):
    path = ("security.memory_write_approval" if name == "memory"
            else "security.skills_write_approval")
    value = schema.get_path(doc, path, None)
    if value is None:
        sec = doc.get(name)
        if isinstance(sec, dict) and "write_approval" in sec:
            value = sec["write_approval"]
    if value is None and "write_approval" in doc:
        value = doc["write_approval"]
    out = schema.as_bool(value, default)
    return bool(out)


def build_doc(disk=None):
    """Build the complete nested config document from live globals."""
    if disk is None:
        try:
            disk = read_doc()
        except Exception:
            disk = {}
    if not isinstance(disk, dict):
        disk = {}
    doc = {"_config_version": CONFIG_VERSION}
    for field in schema.FIELDS:
        key = field["key"]
        if key == "security.memory_write_approval":
            value = _legacy_approval(disk, "memory", False)
        elif key == "security.skills_write_approval":
            value = _legacy_approval(disk, "skills", True)
        else:
            value = _value_for_key(key)
            if value is None:
                value = field.get("default", "")
        schema.set_path(doc, key, value)
    # Preserve unknown keys from the file (hand-added experiments, future
    # settings) so a form save never silently deletes them.
    for key in disk:
        if key == "_config_version":
            continue
        if key not in doc:
            doc[key] = disk[key]
        elif isinstance(disk[key], dict) and isinstance(doc.get(key), dict):
            for sub in disk[key]:
                if sub not in doc[key]:
                    doc[key][sub] = disk[key][sub]
    if not isinstance(doc.get("tools"), dict):
        doc["tools"] = {}
    doc["tools"]["mask"] = int(gToolsMask)
    return doc


def _known_subkeys():
    known = {}
    for field in schema.FIELDS:
        cat, sub = field["key"].split(".", 1)
        if cat not in known:
            known[cat] = {}
        known[cat][sub] = True
    return known


_KNOWN_SUBKEYS = _known_subkeys()


def _normalize_doc(doc, strict=True):
    """Validate/clamp a nested document and fill defaults for missing fields.

    ``strict=False`` is used by the boot loader: a hand-edited typo in one
    field must fall back to that field's default instead of aborting boot and
    entering the reset loop. Saves stay strict so the API can return 400.
    """
    if not isinstance(doc, dict):
        raise ValueError("configuration must be a mapping")
    out = {"_config_version": CONFIG_VERSION}
    for field in schema.FIELDS:
        kind = field.get("type", "string")
        if kind == "readonly":
            continue
        value = schema.get_path(doc, field["key"], None)
        if value is None:
            value = field.get("default", "")
        try:
            value = schema.normalize_value(field, value)
        except ValueError as e:
            if strict:
                raise
            print("[config] invalid %s: %s (using default)"
                  % (field["key"], str(e)[:80]))
            value = field.get("default", "")
        schema.set_path(out, field["key"], value)
    # auth token is readonly in the form but still stored in YAML
    token = schema.get_path(doc, "security.auth_token", "")
    if token is None:
        token = ""
    token = str(token).strip()
    if len(token) > 128:
        token = token[:128]
    schema.set_path(out, "security.auth_token", token)
    # network names have hard length limits in the WiFi stack
    schema.set_path(out, "network.mdns_name",
                    _mdns_name(schema.get_path(out, "network.mdns_name", MDNS_NAME)))
    schema.set_path(out, "network.ap_ssid",
                    _ap_ssid(schema.get_path(out, "network.ap_ssid", AP_SSID)))
    # "keep" must leave rotation headroom below the budget
    max_kb = _clamp_chat_log_max_kb(
        schema.get_path(out, "chat.log_max_kb", DEFAULT_CHAT_LOG_MAX_KB))
    keep_kb = _clamp_chat_log_keep_kb(
        schema.get_path(out, "chat.log_keep_kb", DEFAULT_CHAT_LOG_KEEP_KB), max_kb)
    schema.set_path(out, "chat.log_max_kb", max_kb)
    schema.set_path(out, "chat.log_keep_kb", keep_kb)
    # Preserve unknown keys inside known categories and at the top level.
    for cat in schema.CATEGORY_ORDER:
        src = doc.get(cat)
        if not isinstance(src, dict):
            continue
        known = _KNOWN_SUBKEYS.get(cat, {})
        for sub in src:
            if sub not in known:
                out.setdefault(cat, {})[sub] = src[sub]
    for key in doc:
        if key == "_config_version" or key in schema.CATEGORY_ORDER:
            continue
        out[key] = doc[key]
    # Only keep tools.mask when the document actually has one. A missing
    # mask must stay missing so _apply_doc can apply the computed default
    # (all tools except default_off ones) instead of treating an inherited
    # all-on global as an explicit user choice.
    if isinstance(doc.get("tools"), dict):
        tools = out.get("tools")
        if not isinstance(tools, dict):
            tools = {}
        mask = schema.get_path(doc, "tools.mask", None)
        if mask is not None:
            try:
                mask = int(mask)
            except Exception:
                mask = int(gToolsMask)
            tools["mask"] = mask
        out["tools"] = tools
    return out


def _order_add(order, path, key):
    keys = order.get(path)
    if keys is None:
        keys = []
        order[path] = keys
    if key not in keys:
        keys.append(key)


_DUMP_ORDER = {"": ["_config_version"]}
for _field in schema.FIELDS:
    _parent = ""
    for _part in _field["key"].split("."):
        _order_add(_DUMP_ORDER, _parent, _part)
        _parent = _part if _parent == "" else _parent + "." + _part
_order_add(_DUMP_ORDER, "", "tools")
_order_add(_DUMP_ORDER, "tools", "mask")


def dump_doc(doc):
    """Render the config document as commented, hand-editable YAML."""
    lines = [
        "# Talaria Agent (micro) - configuration",
        "# Edit by hand or use Config in the dashboard. Secrets are stored here.",
        "# The dashboard masks them as **** unless you press Reveal.",
        "",
        "_config_version: %d" % CONFIG_VERSION,
        "",
    ]
    for cat in schema.CATEGORY_ORDER:
        sec = doc.get(cat)
        if not isinstance(sec, dict):
            continue
        meta = schema.CATEGORIES.get(cat, {})
        lines.append("# " + "=" * 70)
        lines.append("# " + str(meta.get("label", cat)))
        if meta.get("description"):
            lines.append("# " + str(meta["description"]))
        lines.append("# " + "=" * 70)
        lines.append(yamlish.dumps({cat: sec}, _DUMP_ORDER).rstrip("\n"))
        lines.append("")
    rest = {}
    for key in doc:
        if key == "_config_version" or key in schema.CATEGORY_ORDER:
            continue
        rest[key] = doc[key]
    if rest:
        lines.append("# " + "=" * 70)
        lines.append("# Advanced")
        lines.append("# " + "=" * 70)
        lines.append(yamlish.dumps(rest, _DUMP_ORDER).rstrip("\n"))
        lines.append("")
    return "\n".join(lines) + "\n"


def _resolve_tools_mask(doc, default_new, off_bits):
    m = schema.get_path(doc, "tools.mask", None)
    try:
        m = int(m)
    except Exception:
        m = default_new
    if m == 0:
        return default_new
    # Auto-enable newly added tools when the stored value was an old "all on"
    # mask. Deliberate default_off bits stay exactly as stored.
    try:
        from agent_tools import TOOL_COUNT
        for k in range(1, TOOL_COUNT):
            old_all = (1 << k) - 1 if k < 32 else 0xFFFFFFFF
            if m == old_all:
                m = default_new | (m & off_bits)
                break
    except Exception:
        pass
    return m


def _apply_doc(doc):
    """Load a normalized document into the module globals."""
    global cfgSsid, cfgPass, cfgEndpoint, cfgApiKey, cfgModel, cfgAuthToken
    global cfgFallbackEndpoint, cfgFallbackKey, cfgFallbackModel, agent_max_iters
    global cfgChatEntryChars, cfgChatLogMaxKB, cfgChatLogKeepKB, cfgChatRestoreTurns
    global cfgThemeScheme, cfgThemeFontHeaders, cfgThemeHeadersSize
    global cfgThemeFontBody, cfgThemeBodySize, cfgThemeFontMono, cfgThemeMonoSize
    global cfgMdnsName, cfgApSsid, gToolsMask
    cfgSsid = _text(schema.get_path(doc, "network.wifi_ssid", ""))
    cfgPass = _text(schema.get_path(doc, "network.wifi_pass", ""))
    cfgEndpoint = _text(schema.get_path(doc, "agent.endpoint", ""))
    cfgApiKey = _text(schema.get_path(doc, "agent.api_key", ""))
    cfgModel = _text(schema.get_path(doc, "agent.model", "gpt-4o-mini"),
                     "gpt-4o-mini")
    if not cfgModel:
        cfgModel = "gpt-4o-mini"
    cfgAuthToken = _text(schema.get_path(doc, "security.auth_token", ""))
    cfgFallbackEndpoint = _text(schema.get_path(doc, "fallback.endpoint", ""))
    cfgFallbackKey = _text(schema.get_path(doc, "fallback.api_key", ""))
    cfgFallbackModel = _text(schema.get_path(doc, "fallback.model", ""))
    cfgMdnsName = _mdns_name(schema.get_path(doc, "network.mdns_name", MDNS_NAME))
    cfgApSsid = _ap_ssid(schema.get_path(doc, "network.ap_ssid", AP_SSID))
    agent_max_iters = _clamp_iters(
        schema.get_path(doc, "agent.max_iters", 3), 3)
    cfgChatEntryChars = _clamp_chat_entry_chars(
        schema.get_path(doc, "chat.entry_chars", DEFAULT_CHAT_ENTRY_CHARS))
    cfgChatLogMaxKB = _clamp_chat_log_max_kb(
        schema.get_path(doc, "chat.log_max_kb", DEFAULT_CHAT_LOG_MAX_KB))
    cfgChatLogKeepKB = _clamp_chat_log_keep_kb(
        schema.get_path(doc, "chat.log_keep_kb", DEFAULT_CHAT_LOG_KEEP_KB),
        cfgChatLogMaxKB)
    cfgChatRestoreTurns = _clamp_chat_restore_turns(
        schema.get_path(doc, "chat.restore_turns", DEFAULT_CHAT_RESTORE_TURNS))
    cfgThemeScheme = _theme_scheme(
        schema.get_path(doc, "theme.color_scheme", DEFAULT_THEME_SCHEME))
    cfgThemeFontHeaders = _theme_font(
        schema.get_path(doc, "theme.font_headers", DEFAULT_THEME_FONT_HEADERS),
        schema.THEME_HEADERS_FONT_OPTIONS)
    cfgThemeHeadersSize = _clamp_theme_size(
        schema.get_path(doc, "theme.font_headers_size",
                        DEFAULT_THEME_HEADERS_SIZE),
        THEME_HEADERS_SIZE_MIN, THEME_HEADERS_SIZE_MAX,
        DEFAULT_THEME_HEADERS_SIZE)
    cfgThemeFontBody = _theme_font(
        schema.get_path(doc, "theme.font_body", DEFAULT_THEME_FONT_BODY),
        schema.THEME_BODY_FONT_OPTIONS)
    cfgThemeBodySize = _clamp_theme_size(
        schema.get_path(doc, "theme.font_body_size", DEFAULT_THEME_BODY_SIZE),
        THEME_BODY_SIZE_MIN, THEME_BODY_SIZE_MAX, DEFAULT_THEME_BODY_SIZE)
    cfgThemeFontMono = _theme_font(
        schema.get_path(doc, "theme.font_mono", DEFAULT_THEME_FONT_MONO),
        schema.THEME_MONO_FONT_OPTIONS)
    cfgThemeMonoSize = _clamp_theme_size(
        schema.get_path(doc, "theme.font_mono_size", DEFAULT_THEME_MONO_SIZE),
        THEME_MONO_SIZE_MIN, THEME_MONO_SIZE_MAX, DEFAULT_THEME_MONO_SIZE)
    try:
        from agent_tools import all_tools_mask, TOOL_REGISTRY
        all_on = all_tools_mask()
    except Exception:
        all_on = 0x3FF
        TOOL_REGISTRY = []
    off_bits = 0
    for index, tool in enumerate(TOOL_REGISTRY):
        try:
            if tool.get("default_off"):
                off_bits |= 1 << index
        except Exception:
            pass
    default_new = all_on & ~off_bits
    gToolsMask = _resolve_tools_mask(doc, default_new, off_bits)


def loadConfig():
    """Load config.yaml into globals, migrating config.json on first boot."""
    doc, source = _read_with_source()
    if source == "json" and doc:
        try:
            normalized = _normalize_doc(doc, strict=False)
            _write_file(CONFIG_PATH, dump_doc(normalized))
            if _read_file(LEGACY_CONFIG_PATH) is not None:
                try:
                    os.remove(LEGACY_BACKUP_PATH)
                except OSError:
                    pass
                try:
                    os.rename(LEGACY_CONFIG_PATH, LEGACY_BACKUP_PATH)
                except OSError:
                    pass
            print("[config] migrated config.json -> config.yaml")
            doc = normalized
        except Exception as e:
            print("[config] migration failed:", str(e)[:120])
    _apply_doc(_normalize_doc(doc, strict=False))


# ---------------------------------------------------------------------------
# writers used by the flat REST endpoints and the old call sites
# ---------------------------------------------------------------------------

def _save_patch(patch):
    doc = build_doc()
    for flat in patch:
        path = schema.FLAT_TO_PATH.get(flat, flat)
        schema.set_path(doc, path, patch[flat])
    doc = _normalize_doc(doc)
    _write_file(CONFIG_PATH, dump_doc(doc))
    _apply_doc(doc)
    return doc


def save_doc(doc, raw_text=None):
    """Apply a nested document, write YAML, and refresh globals."""
    normalized = _normalize_doc(doc)
    text = raw_text if raw_text is not None else dump_doc(normalized)
    _write_file(CONFIG_PATH, text)
    _apply_doc(normalized)
    return normalized


def _mask_secret(key, value):
    if not value:
        return ""
    if key == "agent.api_key" or key == "fallback.api_key":
        return maskedKey(value)
    return "****"


def _live_secret(key):
    if key == "agent.api_key":
        return cfgApiKey
    if key == "fallback.api_key":
        return cfgFallbackKey
    if key == "network.wifi_pass":
        return cfgPass
    if key == "security.auth_token":
        return cfgAuthToken
    return ""


def save_raw_yaml(text):
    """Parse a full YAML document and persist it.

    Masked secret placeholders (the redacted YAML view) are replaced with the
    live values before writing. When the submitted document normalizes
    identically, the original text is written back verbatim so hand-written
    comments survive a save.
    """
    before_net = (cfgSsid, cfgPass, cfgMdnsName, cfgApSsid)
    doc = yamlish.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("YAML must be a mapping")
    if not doc:
        raise ValueError("YAML is empty")
    masked = False
    for key in schema.YAML_SECRET_KEYS:
        value = schema.get_path(doc, key, None)
        if isinstance(value, str) and "****" in value:
            schema.set_path(doc, key, _live_secret(key))
            masked = True
    normalized = _normalize_doc(doc)
    raw_out = None
    if not masked and normalized == doc:
        raw_out = text
    save_doc(normalized, raw_out)
    restart = before_net != (cfgSsid, cfgPass, cfgMdnsName, cfgApSsid)
    return {"doc": normalized, "masked": masked,
            "raw_preserved": raw_out is not None, "restart": restart}


def save_form(values):
    """Apply a dotted-key form payload. Blank secret values keep the old key."""
    doc = build_doc()
    before = build_doc()
    for key in values:
        field = schema.FIELD_MAP.get(key)
        if field is None:
            raise ValueError("unknown config key: %s" % key)
        if field.get("type") == "readonly":
            continue
        value = values[key]
        if field.get("type") == "secret":
            if value is None:
                continue
            text = str(value)
            if text.strip() == "" or "****" in text:
                continue
            value = text
        value = schema.normalize_value(field, value)
        schema.set_path(doc, key, value)
    doc = _normalize_doc(doc)
    _write_file(CONFIG_PATH, dump_doc(doc))
    _apply_doc(doc)
    restart = False
    for field in schema.FIELDS:
        if not field.get("restart"):
            continue
        if (schema.get_path(before, field["key"], None)
                != schema.get_path(doc, field["key"], None)):
            restart = True
    return {"doc": doc, "restart": restart}


def yaml_text(redact=True):
    """Return the YAML shown in the raw editor and whether it was redacted."""
    raw = _read_file(CONFIG_PATH)
    if raw is None:
        raw = dump_doc(build_doc())
    if not redact:
        return raw, False
    try:
        doc = yamlish.loads(raw)
    except Exception:
        doc = build_doc()
    if not isinstance(doc, dict):
        doc = build_doc()
    for key in schema.YAML_SECRET_KEYS:
        value = schema.get_path(doc, key, None)
        if value:
            schema.set_path(doc, key, _mask_secret(key, value))
    return dump_doc(doc), True


# ---------------------------------------------------------------------------
# helpers shared with the API / form page
# ---------------------------------------------------------------------------

def get_approval(name, default=False):
    """Read a write-approval toggle without requiring loadConfig()."""
    doc = read_doc()
    return _legacy_approval(doc, name, default)


def saveApprovals(mem=None, sk=None):
    patch = {}
    if mem is not None:
        patch["memory.write_approval"] = bool(mem)
    if sk is not None:
        patch["skills.write_approval"] = bool(sk)
    if patch:
        _save_patch(patch)


def form_payload():
    """Schema + current values for the Config form."""
    doc = build_doc()
    fields = []
    for field in schema.FIELDS:
        item = {}
        for key in field:
            if key != "default":
                item[key] = field[key]
        value = schema.get_path(doc, field["key"], field.get("default"))
        kind = field.get("type", "string")
        if kind == "secret":
            item["value"] = ""
            item["has_value"] = bool(value)
            item["masked"] = _mask_secret(field["key"], value)
        elif kind == "readonly":
            if field["key"] == "security.auth_token":
                item["value"] = "configured" if cfgAuthToken else "open"
                item["has_value"] = bool(cfgAuthToken)
            else:
                item["value"] = value
        elif kind == "number":
            try:
                item["value"] = int(value)
            except Exception:
                item["value"] = int(field.get("default", 0))
        elif kind == "boolean":
            item["value"] = bool(value)
        else:
            item["value"] = "" if value is None else str(value)
        fields.append(item)
    categories = []
    for cat in schema.CATEGORY_ORDER:
        meta = schema.CATEGORIES.get(cat, {})
        categories.append({"id": cat,
                           "label": meta.get("label", cat),
                           "description": meta.get("description", "")})
    return {"path": CONFIG_PATH, "version": CONFIG_VERSION,
            "categories": categories, "fields": fields}


# ---------------------------------------------------------------------------
# older flat save helpers (kept because the REST API and tests use them)
# ---------------------------------------------------------------------------

def saveToolsMask(m):
    global gToolsMask
    gToolsMask = int(m)
    _save_patch({"tools_mask": int(m)})


def saveChatEntryChars(n):
    """Persist the per-message chat-log cap. Returns the clamped value."""
    global cfgChatEntryChars
    cfgChatEntryChars = _clamp_chat_entry_chars(n, cfgChatEntryChars)
    _save_patch({"chat_entry_chars": cfgChatEntryChars})
    return cfgChatEntryChars


def saveChatStorage(max_kb=None, keep_kb=None, restore_turns=None):
    """Persist the rolling-log budgets. Returns the clamped values.

    Any argument left as None keeps its current value. Lowering max_kb also
    lowers keep_kb when it would no longer leave rotation headroom.
    """
    global cfgChatLogMaxKB, cfgChatLogKeepKB, cfgChatRestoreTurns
    m = (_clamp_chat_log_max_kb(max_kb, cfgChatLogMaxKB)
         if max_kb is not None else cfgChatLogMaxKB)
    k = _clamp_chat_log_keep_kb(
        keep_kb if keep_kb is not None else cfgChatLogKeepKB, m)
    r = (_clamp_chat_restore_turns(restore_turns, cfgChatRestoreTurns)
         if restore_turns is not None else cfgChatRestoreTurns)
    cfgChatLogMaxKB, cfgChatLogKeepKB, cfgChatRestoreTurns = m, k, r
    _save_patch({"chat_log_max_kb": m, "chat_log_keep_kb": k,
                 "chat_restore_turns": r})
    return {"chat_log_max_kb": cfgChatLogMaxKB,
            "chat_log_keep_kb": cfgChatLogKeepKB,
            "chat_restore_turns": cfgChatRestoreTurns}


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


def saveAgentOnly(endpoint, key, model, fallback_endpoint=None,
                  fallback_key=None, fallback_model=None, max_iters=None):
    global cfgEndpoint, cfgApiKey, cfgModel
    global cfgFallbackEndpoint, cfgFallbackKey, cfgFallbackModel, agent_max_iters
    m = (model or "").strip() or "gpt-4o-mini"
    patch = {"api_endpoint": endpoint or "", "api_key": key or "", "api_model": m}
    # None = arg absent (old 3-arg callers preserve current values).
    # Empty string = explicitly cleared.
    if fallback_endpoint is not None:
        cfgFallbackEndpoint = (fallback_endpoint or "").strip()
        patch["fallback_endpoint"] = cfgFallbackEndpoint
    if fallback_key is not None:
        cfgFallbackKey = (fallback_key or "").strip()
        patch["fallback_key"] = cfgFallbackKey
    if fallback_model is not None:
        cfgFallbackModel = (fallback_model or "").strip()
        patch["fallback_model"] = cfgFallbackModel
    if max_iters is not None:
        agent_max_iters = _clamp_iters(max_iters, agent_max_iters)
        patch["agent_max_iters"] = agent_max_iters
    _save_patch(patch)
    cfgEndpoint, cfgApiKey = endpoint or "", key or ""
    cfgModel = m


# ---------------------------------------------------------------------------
# URL helpers / masking (unchanged)
# ---------------------------------------------------------------------------

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
