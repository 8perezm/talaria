# tool_blink — blink a pin N times, ends LOW. Blocking (<=15s).
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import pinCanWrite
    out = {}
    try:
        pin = int(args.get("pin", 2))
    except Exception:
        pin = 2
    try:
        count = int(args.get("count", 5))
    except Exception:
        count = 5
    try:
        onms = int(args.get("on_ms", 200))
    except Exception:
        onms = 200
    try:
        offms = int(args.get("off_ms", 200))
    except Exception:
        offms = 200
    if not pinCanWrite(pin):
        out["error"] = "pin not allowed for output"
    else:
        if count < 1:
            count = 1
        if count > 20:
            count = 20
        if onms < 50:
            onms = 50
        if onms > 1000:
            onms = 1000
        if offms < 50:
            offms = 50
        if offms > 1000:
            offms = 1000
        if count * (onms + offms) > 15000:
            count = 15000 // (onms + offms)
        if count < 1:
            count = 1
        try:
            import time
            sleep_ms = getattr(time, "sleep_ms", None)
            from machine import Pin
            p = Pin(pin, Pin.OUT)
            for _ in range(count):
                p.value(1)
                if sleep_ms:
                    sleep_ms(onms)
                else:
                    time.sleep(onms / 1000.0)
                p.value(0)
                if sleep_ms:
                    sleep_ms(offms)
                else:
                    time.sleep(offms / 1000.0)
            out["ok"] = True
            out["pin"] = pin
            out["blinks"] = count
        except Exception as e:
            out["error"] = "blink failed: %s" % str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "blink",
    "ui_hint": "Blink a pin N times",
    "description": "Blink a GPIO pin N times with visible timing (preferred over repeated gpio_write for blinking). Ends LOW. Allowed pins 2,4,5,12-19,21-23,25-27,32,33 (classic) / S3 0-18,21,35-48.",
    "parameters": {
        "type": "object",
        "properties": {
            "pin": {"type": "integer"},
            "count": {"type": "integer"},
            "on_ms": {"type": "integer"},
            "off_ms": {"type": "integer"},
        },
        "required": ["pin"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
