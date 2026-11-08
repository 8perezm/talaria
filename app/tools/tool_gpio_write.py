# tool_gpio_write — set a GPIO output level.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import pinCanWrite
    out = {}
    try:
        pin = int(args.get("pin", -1))
    except Exception:
        pin = -1
    try:
        lvl = int(args.get("level", -1))
    except Exception:
        lvl = -1
    if not pinCanWrite(pin):
        out["error"] = "pin not allowed for output"
    elif lvl not in (0, 1):
        out["error"] = "level must be 0 or 1"
    else:
        try:
            from machine import Pin
            p = Pin(pin, Pin.OUT)
            p.value(lvl)
            out["ok"] = True
            out["pin"] = pin
            out["level"] = lvl
        except Exception as e:
            out["error"] = "gpio error: %s" % str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "gpio_write",
    "ui_hint": "Digital out (safe pins)",
    "description": "Set GPIO output level. Allowed pins 2,4,5,12-19,21-23,25-27,32,33 (classic) / 0-18,21,35-48 (S3, except USB 19/20).",
    "parameters": {
        "type": "object",
        "properties": {"pin": {"type": "integer"}, "level": {"type": "integer"}},
        "required": ["pin", "level"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
