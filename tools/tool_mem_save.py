# tool_mem_save — save one durable fact (<=500 chars).
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    from agent_tools import appendMemoryFact
    out = {}
    t = args.get("text", "") if isinstance(args, dict) else ""
    try:
        out["ok"] = bool(appendMemoryFact(str(t)))
    except Exception as e:
        out["error"] = str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "mem_save",
    "ui_hint": "Save a memory fact",
    "description": "Save a durable user preference/fact (<=500 chars).",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
