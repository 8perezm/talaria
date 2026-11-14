# patch_file.py — unique-substring single-span patch (Phase 7). Slot 21.
# {path, old, new}: old must occur EXACTLY once (skillstore.py pattern —
# ambiguous matches name their count so the model widens the span).
# checkpoint.backup(path) first, same refusals as write_file. File and
# result both capped at 4KB (the tool cap, not the 200KB Explorer cap).
# Validation errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def patch(path, old, new):
    import fsutil as _m
    import checkpoint as _cp
    n = _m.tool_path(_m.norm(path))
    if n is None or not n:
        return {"success": False, "error": "invalid path"}
    werr = _m.write_refusal(n)
    if werr:
        return {"success": False, "error": werr}
    try:
        old_s = str(old or "")
        new_s = str(new or "")
    except Exception:
        return {"success": False, "error": "old/new text required"}
    if not old_s:
        return {"success": False,
                "error": ("'patch' needs old - a short unique substring of "
                          "the file. Reissue with old copied verbatim from "
                          "read_file output.")}
    if not new_s:
        return {"success": False, "error": "new text is required for 'patch'."}
    fp = _m.full(n)
    if _m.is_dir(fp) is None:
        return {"success": False, "error": "not found"}
    if _m.is_dir(fp):
        return {"success": False, "error": "is a directory"}
    if _m.stat_size(fp) > _m.TOOL_FILE_MAX:
        return {"success": False,
                "error": "file too large for patch (%dB, max %dB) - read it "
                         "in slices and rewrite via write_file"
                         % (_m.stat_size(fp), _m.TOOL_FILE_MAX)}
    res, err, _ = _m.read_text(n, _m.TOOL_FILE_MAX + 1)
    if err:
        return {"success": False, "error": err}
    cur = res["content"]
    c = cur.count(old_s)
    if c == 0:
        return {"success": False,
                "error": ("No match for '%s' in '/%s'. Copy old verbatim "
                          "from read_file output." % (old_s[:60], n))}
    if c > 1:
        return {"success": False,
                "error": ("'%s' appears %d times in '/%s'. Include more "
                          "surrounding text so old occurs once."
                          % (old_s[:60], c, n))}
    after = cur.replace(old_s, new_s, 1)
    if after == cur:
        return {"success": False, "error": "Patch is a no-op."}
    try:
        nbytes = len(after.encode("utf-8"))
    except Exception:
        nbytes = len(after)
    if nbytes > _m.TOOL_FILE_MAX:
        return {"success": False,
                "error": "patched file too large (%dB, max %dB) - use a "
                         "smaller span" % (nbytes, _m.TOOL_FILE_MAX)}
    bk = _cp.backup(n)
    if not bk.get("success") and _m.is_dir(_m.full(n)) is False:
        return {"success": False, "error": bk.get("error", "backup failed")}
    err = _m.write_text(n, after, _m.TOOL_FILE_MAX)
    if err:
        return {"success": False, "error": err}
    return {"success": True, "path": "/" + n, "size": nbytes,
            "backed_up": bool(bk.get("backed_up"))}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(patch(args.get("path", ""),
                                args.get("old", ""),
                                args.get("new", "")))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "patch_file failed: %s" % str(e)[:120]})


TOOL = {
    "name": "patch_file",
    "ui_hint": "Patch one unique span of a workspace/ file (.bak first)",
    "description": ("Patch one span of a workspace file (opt/data/workspace/, "
                    "shown as /workspace/ in Files; bare names and "
                    "workspace/... map there): {path, old, new} "
                    "where old is a short substring occurring EXACTLY once "
                    "(read the file first, copy verbatim; widen the span "
                    "when told it is ambiguous). A .bak checkpoint is kept "
                    "first. Same managed-state refusals as write_file. "
                    "Files over 16KB cannot be patched — rewrite instead."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["path", "old", "new"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
