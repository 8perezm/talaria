# tool_gpio_read — read a GPIO level.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import pinCanRead
    out = {}
    try:
        pin = int(args.get("pin", -1))
    except Exception:
        pin = -1
    if not pinCanRead(pin):
        out["error"] = "pin not allowed"
    else:
        try:
            from machine import Pin
            p = Pin(pin, Pin.IN)
            out["pin"] = pin
            out["level"] = p.value()
        except Exception as e:
            out["error"] = "gpio error: %s" % str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "gpio_read",
    "ui_hint": "Digital in",
    "description": "Read GPIO level.",
    "parameters": {
        "type": "object",
        "properties": {"pin": {"type": "integer"}},
        "required": ["pin"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
