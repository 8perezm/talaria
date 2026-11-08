# todo.py — parent-local plan state (Mini Hermes Phase 6). Slot 16.
# Single-user device: one module-global list, no sessions, no flash writes.
# In-memory only — a reboot clears it; the parent re-states the plan each turn.
# Ops: {op: list|add|done|clear, text?, id?}. Bounded: max 20 items,
# text <= 200 chars. Validation errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json

MAX_ITEMS = 20
TEXT_MAX = 200

_items = []
_next_id = 1


def _reset():
    """Test hook: empty the list and restart ids. In-memory only."""
    global _items, _next_id
    _items = []
    _next_id = 1


def list_items():
    out = []
    for it in _items:
        out.append({"id": it["id"], "text": it["text"], "done": it["done"]})
    return {"success": True, "items": out, "count": len(out),
            "max_items": MAX_ITEMS}


def add(text):
    global _next_id
    try:
        t = str(text or "").strip()
    except Exception:
        return {"success": False, "error": "text is required"}
    if not t:
        return {"success": False, "error": "text is required"}
    if len(t) > TEXT_MAX:
        return {"success": False,
                "error": "text too long (%d chars, max %d)" % (len(t), TEXT_MAX)}
    if len(_items) >= MAX_ITEMS:
        return {"success": False,
                "error": "todo list full (%d max); mark items done or clear first"
                         % MAX_ITEMS}
    item = {"id": _next_id, "text": t, "done": False}
    _next_id += 1
    _items.append(item)
    return {"success": True,
            "item": {"id": item["id"], "text": item["text"],
                     "done": item["done"]},
            "count": len(_items)}


def done(item_id):
    try:
        want = int(item_id)
    except Exception:
        return {"success": False, "error": "id is required (see list)"}
    for it in _items:
        if it["id"] == want:
            it["done"] = True
            return {"success": True,
                    "item": {"id": it["id"], "text": it["text"],
                             "done": it["done"]}}
    return {"success": False,
            "error": "unknown todo id '%s' (see list)" % str(item_id)[:20]}


def clear_all():
    global _items
    n = len(_items)
    try:
        del _items[:]
    except Exception:
        _items = []
    return {"success": True, "cleared": n, "count": 0}


def handle(args):
    if not isinstance(args, dict):
        args = {}
    try:
        op = str(args.get("op", "list") or "list").strip().lower()
    except Exception:
        op = "list"
    if op == "list":
        return list_items()
    if op == "add":
        return add(args.get("text", ""))
    if op == "done":
        return done(args.get("id"))
    if op == "clear":
        return clear_all()
    return {"success": False,
            "error": "Unknown op '%s'. Use: list, add, done, clear" % op[:20]}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(handle(args))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "todo failed: %s" % str(e)[:120]})


TOOL = {
    "name": "todo",
    "ui_hint": "Track multi-step plan items (in-memory, max 20)",
    "description": ("Parent-local plan state for multi-step tasks (in-memory only, "
                    "never flashed; a reboot clears it). Ops: list, add {text}, "
                    "done {id}, clear. Max 20 items, text <= 200 chars. Use to plan "
                    "a task, then mark items done as you finish them."),
    "parameters": {
        "type": "object",
        "properties": {
            "op": {"type": "string",
                   "enum": ["list", "add", "done", "clear"]},
            "text": {"type": "string"},
            "id": {"type": "integer"},
        },
        "required": ["op"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
