# tool_restart — reboot. Requires confirm=true; reboot happens after reply.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import agent_tools
    out = {}
    c = args.get("confirm", False) if isinstance(args, dict) else False
    # MicroPython json True/False; also accept "true"/1
    if isinstance(c, str):
        c = c.lower() in ("true", "1", "yes")
    if not c:
        out["error"] = "needs confirm=true"
    else:
        out["ok"] = True
        out["restarting"] = True
        agent_tools.gRestartPending = True
    return json.dumps(out)


TOOL = {
    "name": "restart_device",
    "ui_hint": "Restart (needs confirm)",
    "description": "Restart ESP32. Only when user explicitly asks. Requires confirm=true.",
    "parameters": {
        "type": "object",
        "properties": {"confirm": {"type": "boolean"}},
        "required": ["confirm"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
