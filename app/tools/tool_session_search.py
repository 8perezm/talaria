# tool_session_search — keyword recall across saved conversations. Slot 14.
# {query, limit?} scans the newest session files (opt/data/sessions/*.jsonl;
# case-insensitive AND-of-words, hit-count ranking, recency tiebreak, ±1
# neighbors, ~2KB cap). Use when the user asks about something said earlier —
# especially in another conversation, which injectRecentLog (last-8 of the
# ACTIVE session only) cannot see.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import sessions as _sess
    if not isinstance(args, dict):
        args = {}
    q = args.get("query", args.get("q", args.get("text", "")))
    if q is None:
        q = ""
    q = str(q).strip()
    if not q:
        return json.dumps({"success": False,
                           "error": "query is required"})
    lim = args.get("limit", 5)
    try:
        lim = int(lim)
    except Exception:
        lim = 5
    return json.dumps(_sess.search(q, lim))


TOOL = {
    "name": "session_search",
    "ui_hint": "Search past chat turns (including pre-/new history)",
    "description": ("Search past conversation turns by keyword, including turns from "
                    "before the last /new rotation. AND-of-words match ranked by hit "
                    "count with recency tiebreak; each hit includes its neighboring "
                    "turns. Use when the user refers to something said earlier that "
                    "may have scrolled out of recent context."),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    },
    "run": _run,
    "max_result_chars": 2000,
}
