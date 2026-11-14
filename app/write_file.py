# write_file.py — checkpointed file write (Mini Hermes Phase 7). Slot 20.
# {path, content<=4096B, append=false}: checkpoint.backup(path) FIRST (existing
# file -> path.bak, rotating cap 8), then write. append=true adds to the end
# (skips the backup) and allows an assembled file up to TOOL_FILE_MAX (16KB),
# which is how a long script is built across several model replies. Managed
# state (config.yaml, memory.txt, user.txt, chatlog*.jsonl, cron.json,
# tg.json, bundles.json, pending_*, skills/ and friends) is REFUSED with the
# owning flow named. Validation errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def write(path, content, append=False):
    import fsutil as _m
    import checkpoint as _cp
    n = _m.tool_path(_m.norm(path))
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
        chunk_bytes = len(text.encode("utf-8"))
    except Exception:
        chunk_bytes = len(text)
    if chunk_bytes > _m.TOOL_CONTENT_MAX:
        return {"success": False,
                "error": ("content too large for one call (%dB, max %dB) - "
                          "send it in chunks with append=true"
                          % (chunk_bytes, _m.TOOL_CONTENT_MAX))}
    try:
        if isinstance(append, str):
            ap = append.strip().lower() in ("1", "true", "yes", "on")
        else:
            ap = bool(append)
    except Exception:
        ap = False
    existing = ""
    if ap:
        # append builds a large file across several model calls; each chunk
        # is bounded by the output budget, not by the 4KB single-call cap.
        res, rerr, _size = _m.read_text(n, _m.TOOL_FILE_MAX + 1)
        if res is None and rerr and rerr != "not found":
            return {"success": False, "error": rerr}
        if res is not None:
            existing = res.get("content", "")
            if res.get("truncated"):
                return {"success": False,
                        "error": ("file is already at the %dB append cap - "
                                  "start a new file" % _m.TOOL_FILE_MAX)}
    total = existing + text
    try:
        nbytes = len(total.encode("utf-8"))
    except Exception:
        nbytes = len(total)
    if nbytes > _m.TOOL_FILE_MAX:
        return {"success": False,
                "error": ("file too large (%dB, max %dB) - split it into "
                          "modules or patch a span"
                          % (nbytes, _m.TOOL_FILE_MAX))}
    bk = {"success": True, "backed_up": False}
    if not ap:
        # append skips the .bak: the previous content is a prefix of the new
        # file, and rotating a snapshot per chunk would evict real history.
        bk = _cp.backup(n)
        if not bk.get("success") and _m.is_dir(_m.full(n)) is False:
            return {"success": False, "error": bk.get("error", "backup failed")}
    err = _m.write_text(n, total, _m.TOOL_FILE_MAX)
    if err:
        return {"success": False, "error": err}
    return {"success": True, "path": "/" + n, "size": nbytes,
            "appended": ap, "backed_up": bool(bk.get("backed_up"))}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(write(args.get("path", ""),
                                args.get("content", ""),
                                args.get("append", False)))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "write_file failed: %s" % str(e)[:120]})


TOOL = {
    "name": "write_file",
    "ui_hint": "Write a workspace file (<=4KB per call, append chunks)",
    "description": ("Write a workspace file (page, script, note): "
                    "{path, content, append=false}. CREATE NEW FILES ONLY "
                    "under opt/data/workspace/ (bare names and workspace/... "
                    "map there; shown as /workspace/ in Files). Each call "
                    "may send <=4096B; set append=true to add a chunk to the "
                    "end of an existing file (assembled file <=16KB) - this "
                    "is how a long script is built when one reply is not "
                    "enough. A .bak checkpoint of the old file is kept first "
                    "(append skips it). Managed state (config, memory, logs, "
                    "cron, skills) is refused - each names its owning "
                    "tool/flow. Read the file first, then write the complete "
                    "new content."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean"},
        },
        "required": ["path", "content"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
