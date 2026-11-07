# tool_adc_read — analog read.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import pinCanADC
    out = {}
    try:
        pin = int(args.get("pin", -1))
    except Exception:
        pin = -1
    if not pinCanADC(pin):
        out["error"] = "use ADC pins 32,33,34,35,36,39 (classic) / 1-20 (S3)"
    else:
        try:
            from machine import ADC, Pin
            adc = ADC(Pin(pin))
            try:
                adc.atten(ADC.ATTN_11DB)
            except Exception:
                pass
            out["pin"] = pin
            out["value"] = adc.read()
        except Exception as e:
            out["error"] = "adc error: %s" % str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "adc_read",
    "ui_hint": "Analog (32,33,34,35,36,39 / S3 1-20)",
    "description": "Analog read. Best pins 32,33,34,35,36,39 (classic) / 1-20 (S3).",
    "parameters": {
        "type": "object",
        "properties": {"pin": {"type": "integer"}},
        "required": ["pin"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
