# search_files.py — capped substring search over workspace files. Slot 22.
# {pattern, root="/"} -> {matches: [{file, line, text}], count, truncated}.
# Case-insensitive (sessions.py house style), <=20 hits, skips binary and
# oversize (>32KB) files, never walks above root. Validation errors are
# returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def search(pattern, root="/"):
    import fsutil as _m
    if root is None or (isinstance(root, str) and not root.strip()):
        root = "/"
    return _m.grep_files(pattern, root)


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        root = args.get("root", None)
        if root is None or (isinstance(root, str) and not root.strip()):
            # Default to the user-data home, not the whole flash: the old "/"
            # default walked app/, www/ and sessions/ on every search and
            # could take long enough to trip the tool budget.
            import fsutil as _m
            root = _m.DATA_ROOT
        return json.dumps(search(args.get("pattern", ""), str(root)))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "search_files failed: %s" % str(e)[:120]})


TOOL = {
    "name": "search_files",
    "ui_hint": "Search opt/data files (max 20 hits)",
    "description": ("Search files for a substring (case-insensitive): "
                    "{pattern, root=\"opt/data\"}. The default root is the "
                    "user-data home (workspace/, sessions/, skills/); pass "
                    "a subdirectory or \"/\" (whole flash, slower). Returns "
                    "up to 20 file:line matches with snippets; binary and "
                    "oversize files are skipped, the walk never leaves "
                    "root, and secrets/partial writes are never returned. "
                    "Use to locate code or text before reading it."),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "root": {"type": "string"},
        },
        "required": ["pattern"],
    },
    "run": _run,
    "max_result_chars": 2600,
}
