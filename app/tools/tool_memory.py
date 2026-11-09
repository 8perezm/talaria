# tool_memory — two-store curated memory: add/patch/remove (+batch).
# Slot 11. mem_save/mem_read stay as compat delegates (model + UI use them).
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import memory as _mem
    if not isinstance(args, dict):
        args = {}
    ops = args.get("operations")
    act = str(args.get("action", "") or "").strip().lower()
    tgt = args.get("target", "device")
    if tgt is None:
        tgt = "device"
    tgt = str(tgt)
    # Hermes shape {target, operations} without a top-level action.
    if ops is not None:
        if not isinstance(ops, list):
            return json.dumps({"success": False, "error": "operations must be a list"})
        if act in ("", "batch"):
            return json.dumps(_mem.apply_batch(tgt, ops))
        return json.dumps({"success": False,
                           "error": "action must be 'batch' when operations is set"})
    if act == "add":
        content = args.get("content", args.get("text", args.get("new_text", "")))
        if content is None:
            content = ""
        return json.dumps(_mem.add(tgt, str(content)))
    if act == "patch":
        content = args.get("content", args.get("text", args.get("new_text", "")))
        old = args.get("old_text", "")
        if content is None:
            content = ""
        if old is None:
            old = ""
        return json.dumps(_mem.patch(tgt, str(old), str(content)))
    if act == "remove":
        old = args.get("old_text", "")
        if old is None:
            old = ""
        return json.dumps(_mem.remove(tgt, str(old)))
    if act == "batch":
        return json.dumps({"success": False,
                           "error": "batch needs an operations list of {action, content?, old_text?}"})
    return json.dumps({"success": False,
                       "error": "Unknown action '%s'. Use: add, patch, remove, batch" % act[:40]})


TOOL = {
    "name": "memory",
    "ui_hint": "Add/patch/remove a memory fact",
    "description": ("Save durable facts to persistent memory (targets: device, user). "
                    "Single op {action: add|patch|remove, ...} or one batch {action: batch, "
                    "operations: [...]} — the batch limit is checked only on the final result, "
                    "so free space and add in ONE call when full."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "patch", "remove", "batch"]},
            "target": {"type": "string", "enum": ["device", "user"]},
            "text": {"type": "string"},
            "content": {"type": "string"},
            "old_text": {"type": "string"},
            "operations": {"type": "array",
                           "items": {"type": "object",
                                    "properties": {
                                        "action": {"type": "string"},
                                        "text": {"type": "string"},
                                        "content": {"type": "string"},
                                        "old_text": {"type": "string"}}}},
        },
        "required": ["action", "target"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
