# read_file.py — sliced file read (Mini Hermes Phase 7). Slot 19.
# {path, offset=0, limit=4096} -> {content, size, truncated}. Single-pass
# chunked reads (fsutil.read_slice) so big logs are pageable, never loaded
# whole. Secrets (config.yaml/config.json/tg.json) and partial writes (*.tmp) are
# REFUSED; .bak snapshots ARE readable (rollback inspection). Validation
# errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def read(path, offset=0, limit=None):
    import fsutil as _m
    n = _m.tool_path(_m.norm(path))
    if n is None or not n:
        return {"success": False, "error": "invalid path"}
    rerr = _m.read_refusal(n)
    if rerr:
        return {"success": False, "error": rerr}
    if limit is None:
        limit = _m.READ_SLICE_DEFAULT
    res, err, size = _m.read_slice(n, offset, limit)
    if err:
        return {"success": False, "error": err, "size": size}
    try:
        off = int(offset)
    except Exception:
        off = 0
    try:
        lim = int(limit)
    except Exception:
        lim = _m.READ_SLICE_DEFAULT
    if lim > _m.READ_SLICE_MAX:
        lim = _m.READ_SLICE_MAX
    return {"success": True, "path": "/" + n, "content": res["content"],
            "size": res["size"], "offset": off, "limit": lim,
            "truncated": res["truncated"]}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(read(args.get("path", ""),
                               args.get("offset", 0),
                               args.get("limit", None)))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "read_file failed: %s" % str(e)[:120]})


TOOL = {
    "name": "read_file",
    "ui_hint": "Read a workspace file in slices (max 4KB per read)",
    "description": ("Read a workspace file (opt/data/workspace/, shown as "
                    "/workspace/ in Files: code, pages, logs) in slices: "
                    "{path, offset=0, limit=4096 (max 4096)}. Bare names and "
                    "workspace/... mean opt/data/workspace/; other paths "
                    "(app/, www/) are full-flash. Returns "
                    "{content, size, truncated} — page large files with "
                    "offset. Secrets (config.yaml, config.json, tg.json) and partial "
                    "writes (*.tmp) are refused; .bak snapshots are "
                    "readable. Use to inspect a file before editing it."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["path"],
    },
    "run": _run,
    "max_result_chars": 2600,
}
