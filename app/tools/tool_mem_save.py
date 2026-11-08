# tool_mem_save — save one durable fact (compat alias: add to device store).
# Schema and name are stable (model + UI depend on them); behavior delegates
# to memory.py, which owns the store files.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import memory as _mem
    out = {}
    t = args.get("text", "") if isinstance(args, dict) else ""
    try:
        r = _mem.add("device", str(t))
        if r.get("success"):
            out["ok"] = True
            if r.get("duplicate"):
                out["duplicate"] = True
            if r.get("staged"):
                out["staged"] = True
                out["pending_id"] = r.get("pending_id")
            if r.get("message"):
                out["message"] = r["message"]
        else:
            out["ok"] = False
            out["error"] = str(r.get("error", "save failed"))[:300]
            if "need_free" in r:
                out["need_free"] = r["need_free"]
    except Exception as e:
        out["ok"] = False
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
