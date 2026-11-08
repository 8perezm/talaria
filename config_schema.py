# config_schema.py — the one place that describes every config setting.
#
# The Config page, the YAML writer, the legacy config.json migration and the
# REST API all read this module. Adding a new setting is a one-line change
# here (plus reading it in config.py); no UI component needs to know its name.
#
# Field types:
#   string   single-line text
#   text     multi-line text
#   number   integer with optional min/max/step
#   boolean  toggle
#   secret   password input; blank in the form = keep the stored value
#   select   one of `options`
#   readonly display-only (value comes from live state)
#
# `group` is the sub-heading shown inside a category. `restart` marks values
# that only take effect after a reboot (WiFi and discovery settings).

CATEGORY_ORDER = ("agent", "fallback", "network", "chat", "security")

CATEGORIES = {
    "agent": {
        "label": "Agent",
        "description": "Primary model provider and the agent tool loop.",
    },
    "fallback": {
        "label": "Fallback",
        "description": "Secondary provider used only when the primary fails.",
    },
    "network": {
        "label": "Network",
        "description": "WiFi station, setup access point and discovery name.",
    },
    "chat": {
        "label": "Chat",
        "description": "Conversation restore depth and rolling log budgets.",
    },
    "security": {
        "label": "Security",
        "description": "Write approvals and dashboard authentication.",
    },
}

# Dotted path -> legacy flat key used by config.json and the existing REST
# endpoints. Keeping both lets old callers (/api/agent, /api/wifi, tests) work
# while the file on disk moves to nested YAML.
FLAT_TO_PATH = {
    "wifi_ssid": "network.wifi_ssid",
    "wifi_pass": "network.wifi_pass",
    "api_endpoint": "agent.endpoint",
    "api_key": "agent.api_key",
    "api_model": "agent.model",
    "auth_token": "security.auth_token",
    "fallback_endpoint": "fallback.endpoint",
    "fallback_key": "fallback.api_key",
    "fallback_model": "fallback.model",
    "agent_max_iters": "agent.max_iters",
    "chat_entry_chars": "chat.entry_chars",
    "chat_log_max_kb": "chat.log_max_kb",
    "chat_log_keep_kb": "chat.log_keep_kb",
    "chat_restore_turns": "chat.restore_turns",
    "tools_mask": "tools.mask",
    # Hermes-style approvals in JSON lived in nested sections.
    "memory.write_approval": "security.memory_write_approval",
    "skills.write_approval": "security.skills_write_approval",
}

FIELDS = [
    {
        "key": "agent.endpoint",
        "category": "agent",
        "group": "Provider",
        "type": "string",
        "label": "Endpoint",
        "description": "OpenAI-compatible base URL. The client appends "
                       "/models and /chat/completions.",
        "placeholder": "https://api.deepinfra.com/v1/openai",
        "default": "",
    },
    {
        "key": "agent.model",
        "category": "agent",
        "group": "Provider",
        "type": "string",
        "label": "Model",
        "description": "Exact model id used for chat completions.",
        "placeholder": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        "default": "gpt-4o-mini",
    },
    {
        "key": "agent.api_key",
        "category": "agent",
        "group": "Provider",
        "type": "secret",
        "label": "API key",
        "description": "Stored in config.yaml. Leave blank in the form to keep "
                       "the current key.",
        "placeholder": "sk-...",
        "default": "",
    },
    {
        "key": "agent.max_iters",
        "category": "agent",
        "group": "Loop",
        "type": "number",
        "label": "Max tool iterations",
        "description": "Upper bound on tool round trips per turn.",
        "min": 1,
        "max": 5,
        "step": 1,
        "default": 3,
    },
    {
        "key": "fallback.endpoint",
        "category": "fallback",
        "group": "Provider",
        "type": "string",
        "label": "Fallback endpoint",
        "description": "Used when the primary provider fails.",
        "placeholder": "https://openrouter.ai/api/v1",
        "default": "",
    },
    {
        "key": "fallback.model",
        "category": "fallback",
        "group": "Provider",
        "type": "string",
        "label": "Fallback model",
        "description": "Model id on the fallback endpoint.",
        "placeholder": "nousresearch/hermes-4-405b",
        "default": "",
    },
    {
        "key": "fallback.api_key",
        "category": "fallback",
        "group": "Provider",
        "type": "secret",
        "label": "Fallback API key",
        "description": "Leave blank in the form to keep the current key.",
        "placeholder": "sk-...",
        "default": "",
    },
    {
        "key": "network.wifi_ssid",
        "category": "network",
        "group": "Station",
        "type": "string",
        "label": "WiFi SSID",
        "description": "Station network joined at boot.",
        "placeholder": "home-network",
        "restart": True,
        "default": "",
    },
    {
        "key": "network.wifi_pass",
        "category": "network",
        "group": "Station",
        "type": "secret",
        "label": "WiFi password",
        "description": "Leave blank in the form to keep the current password. "
                       "Saving a changed SSID or password requires a restart.",
        "placeholder": "********",
        "strip": False,
        "restart": True,
        "default": "",
    },
    {
        "key": "network.mdns_name",
        "category": "network",
        "group": "Discovery",
        "type": "string",
        "label": "mDNS hostname",
        "description": "Advertised as <name>.local on builds that support mDNS.",
        "placeholder": "esp32-agent",
        "restart": True,
        "default": "esp32-agent",
    },
    {
        "key": "network.ap_ssid",
        "category": "network",
        "group": "Discovery",
        "type": "string",
        "label": "Setup AP SSID",
        "description": "Fallback access point used when WiFi fails.",
        "placeholder": "ESP32-Agent-Setup",
        "restart": True,
        "default": "ESP32-Agent-Setup",
    },
    {
        "key": "chat.entry_chars",
        "category": "chat",
        "group": "Restore",
        "type": "number",
        "label": "Characters per message",
        "description": "Stored in chatlog.jsonl and restored after a reload.",
        "min": 500,
        "max": 20000,
        "step": 500,
        "default": 4000,
    },
    {
        "key": "chat.restore_turns",
        "category": "chat",
        "group": "Restore",
        "type": "number",
        "label": "Turns restored after reload",
        "description": "Replays the last user/assistant exchanges on page load.",
        "min": 1,
        "max": 60,
        "step": 1,
        "default": 20,
    },
    {
        "key": "chat.log_max_kb",
        "category": "chat",
        "group": "Rolling log",
        "type": "number",
        "label": "Log budget (KB)",
        "description": "Rotate chatlog.jsonl when it grows past this size.",
        "min": 64,
        "max": 4096,
        "step": 32,
        "default": 320,
    },
    {
        "key": "chat.log_keep_kb",
        "category": "chat",
        "group": "Rolling log",
        "type": "number",
        "label": "Keep after rotation (KB)",
        "description": "Newest slice kept when rotating; must leave 32 KB of "
                       "headroom below the budget.",
        "min": 32,
        "max": 4064,
        "step": 16,
        "default": 200,
    },
    {
        "key": "security.auth_token",
        "category": "security",
        "group": "Dashboard auth",
        "type": "readonly",
        "label": "Auth token",
        "description": "Managed on the Keys page. Edit it in YAML to rotate it "
                       "by hand; a saved change unlocks this browser with the "
                       "new token automatically.",
        "default": "",
    },
    {
        "key": "security.memory_write_approval",
        "category": "security",
        "group": "Write approvals",
        "type": "boolean",
        "label": "Memory write approval",
        "description": "Stage agent-authored memory changes for review.",
        "default": False,
    },
    {
        "key": "security.skills_write_approval",
        "category": "security",
        "group": "Write approvals",
        "type": "boolean",
        "label": "Skills write approval",
        "description": "Stage agent-authored skills for review.",
        "default": True,
    },
]

FIELD_MAP = {}
for _field in FIELDS:
    FIELD_MAP[_field["key"]] = _field

SECRET_KEYS = tuple(
    _field["key"] for _field in FIELDS if _field.get("type") == "secret"
)

# The auth token is a secret too, but it is displayed readonly in the form.
YAML_SECRET_KEYS = SECRET_KEYS + ("security.auth_token",)


def category_fields(category):
    return [f for f in FIELDS if f["category"] == category]


def as_bool(value, default=None):
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def normalize_value(field, value):
    """Coerce a submitted value to the field's type. Raises ValueError."""
    kind = field.get("type", "string")
    if kind == "readonly":
        return value
    if kind == "boolean":
        out = as_bool(value, None)
        if out is None:
            raise ValueError("%s must be true or false" % field["label"])
        return out
    if kind == "number":
        try:
            if isinstance(value, bool):
                number = 1 if value else 0
            elif isinstance(value, int):
                number = value
            elif isinstance(value, float):
                number = int(value)
            else:
                text = str(value).strip()
                if text == "":
                    raise ValueError
                number = int(float(text))
        except Exception:
            raise ValueError("%s must be a number" % field["label"])
        if "min" in field and number < field["min"]:
            number = field["min"]
        if "max" in field and number > field["max"]:
            number = field["max"]
        return number
    if kind == "select":
        text = "" if value is None else str(value)
        options = field.get("options") or []
        if text not in options:
            raise ValueError("%s must be one of %s" % (field["label"], ", ".join(options)))
        return text
    if kind == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        text = "" if value is None else str(value)
        return [part.strip() for part in text.split(",") if part.strip()]
    # string / text / secret
    if isinstance(value, (dict, list)):
        raise ValueError("%s must be text" % field["label"])
    text = "" if value is None else str(value)
    if field.get("strip", True):
        text = text.strip()
    return text


def get_path(doc, path, default=None):
    """Read a dotted path from nested dicts."""
    node = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_path(doc, path, value):
    """Write a dotted path into nested dicts, creating sections as needed."""
    parts = path.split(".")
    node = doc
    for i in range(len(parts) - 1):
        part = parts[i]
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value
