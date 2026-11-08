# write_file.py — checkpointed file write (Mini Hermes Phase 7). Slot 20.
# {path, content<=4096B}: checkpoint.backup(path) FIRST (existing file ->
# path.bak, rotating cap 8), then write. Managed state (config.yaml,
# memory.txt, user.txt, chatlog*.jsonl, cron.json, tg.json, bundles.json,
# pending_*, skills/ and friends) is REFUSED with the owning flow named.
# Validation errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def write(path, content):
    import fsutil as _m
    import checkpoint as _cp
    n = _m.norm(path)
    if n is None or not n:
        return {"success": False, "error": "invalid path"}
    werr = _m.write_refusal(n)
    if werr:
        return {"success": False, "error": werr}
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except Exception:
            return {"success": False,
                    "error": "binary content not supported here (use upload)"}
    try:
        text = str(content or "")
    except Exception:
        return {"success": False, "error": "content must be a string"}
    if not text:
        return {"success": False, "error": "content is required"}
    try:
        nbytes = len(text.encode("utf-8"))
    except Exception:
        nbytes = len(text)
    if nbytes > _m.TOOL_CONTENT_MAX:
        return {"success": False,
                "error": "content too large (%dB, max %dB)" % (nbytes, _m.TOOL_CONTENT_MAX)}
    bk = _cp.backup(n)
    # Refusals were checked above, so a failure here is IO: do not write
    # without a snapshot when one was possible (missing source already
    # returns success with backed_up False).
    if not bk.get("success") and _m.is_dir(_m.full(n)) is False:
        return {"success": False, "error": bk.get("error", "backup failed")}
    err = _m.write_text(n, text, _m.TOOL_CONTENT_MAX)
    if err:
        return {"success": False, "error": err}
    return {"success": True, "path": "/" + n, "size": nbytes,
            "backed_up": bool(bk.get("backed_up"))}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(write(args.get("path", ""),
                                args.get("content", "")))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "write_file failed: %s" % str(e)[:120]})


TOOL = {
    "name": "write_file",
    "ui_hint": "Write a workspace file under workspace/ (<=4KB, .bak first)",
    "description": ("Write a small workspace file (page, script, note): "
                    "{path, content<=4096B}. CREATE NEW FILES ONLY under "
                    "opt/data/workspace/ (e.g. opt/data/workspace/hello.py, "
                    "shown as /workspace/hello.py in Files) — never at the "
                    "flash root. A .bak checkpoint of the old "
                    "file is kept first (rollback via POST /api/rollback). "
                    "Managed state (config, memory, logs, cron, skills) is "
                    "refused — each names its owning tool/flow. Read the "
                    "file first, then write the complete new content."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
