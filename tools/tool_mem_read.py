# tool_mem_read — read saved memory facts (compat alias: device snapshot).
# Schema and name are stable (model + UI depend on them); behavior delegates
# to memory.py, which owns the store files.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import memory as _mem
    out = {}
    try:
        out["memory"] = _mem.snapshot("device")[:2000]
    except Exception as e:
        out["error"] = str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "mem_read",
    "ui_hint": "Read memory facts",
    "description": "Read saved memory facts.",
    "parameters": {"type": "object", "properties": {}},
    "run": _run,
    "max_result_chars": 1200,
}
