# tool_mem_read — read saved memory facts.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import readMemoryFacts
    out = {}
    try:
        out["memory"] = readMemoryFacts()[:2000]
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
