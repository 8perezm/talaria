# checkpoint.py — .bak snapshots before writes + rollback (Phase 7).
# ONE backup per path (<path>.bak), max MAX_BACKUPS total: exceeding that
# evicts the oldest by mtime (path tiebreak — mtime granularity is coarse).
# MicroPython-safe: chunked copy (2KB), no `re`, bounded lists, lazy imports.
# backup() refuses managed paths (same rules as the write_file tool — those
# files have dedicated flows and need no snapshot); rollback() refuses them
# too. backup() never raises: server.py save/upload handlers call it
# best-effort and proceed with the write regardless.
MAX_BACKUPS = 8
COPY_CHUNK = 2048


def _copy_file(src_full, dst_full):
    """Chunked copy. Returns '' or err text."""
    try:
        f = open(src_full, "rb")
    except Exception as e:
        return "backup read failed: %s" % str(e)[:80]
    try:
        g = open(dst_full, "wb")
    except Exception as e:
        try:
            f.close()
        except Exception:
            pass
        return "backup write failed: %s" % str(e)[:80]
    try:
        while True:
            try:
                chunk = f.read(COPY_CHUNK)
            except TypeError:
                chunk = f.read()  # very old MicroPython read() takes no size
                if chunk:
                    g.write(chunk)
                break
            if not chunk:
                break
            g.write(chunk)
    except Exception as e:
        try:
            f.close()
        except Exception:
            pass
        try:
            g.close()
        except Exception:
            pass
        return "backup copy failed: %s" % str(e)[:80]
    try:
        f.close()
    except Exception:
        pass
    try:
        g.close()
    except Exception:
        pass
    return ""


def _enforce_cap():
    """Delete oldest .bak files beyond MAX_BACKUPS. Returns [evicted paths]."""
    import fsutil as _m
    baks = _m.find_suffix(".bak")
    if len(baks) <= MAX_BACKUPS:
        return []
    info = []
    for b in baks:
        info.append((_m.stat_mtime(_m.full(b)), b))
    # insertion sort by (mtime, path) oldest-first (tiny lists, no key-sort)
    for a in range(len(info)):
        for c in range(a + 1, len(info)):
            if (info[c][0], info[c][1]) < (info[a][0], info[a][1]):
                info[a], info[c] = info[c], info[a]
    evicted = []
    import os
    while len(info) > MAX_BACKUPS:
        _, b = info.pop(0)
        try:
            os.remove(_m.full(b))
            evicted.append("/" + b)
        except Exception:
            pass  # unremovable: dropped from the count, never fatal
    return evicted


def backup(path):
    """Snapshot path -> path.bak BEFORE a write. Never raises.

    Returns {success, backed_up, path?, backup?, evicted?, error?}:
    missing source = success + backed_up False (new file, nothing to snap);
    managed paths (.bak/.tmp sidecars, write-blocklisted state) = refused."""
    import fsutil as _m
    n = _m.norm(path)
    if n is None or not n:
        return {"success": False, "backed_up": False, "error": "invalid path"}
    if n.endswith(".bak") or n.endswith(".tmp"):
        return {"success": False, "backed_up": False,
                "error": "refused: sidecar files are checkpoint-managed, "
                         "never snapshotted"}
    werr = _m.write_refusal(n)
    if werr:
        return {"success": False, "backed_up": False, "error": werr}
    src = _m.full(n)
    d = _m.is_dir(src)
    if d is None:
        return {"success": True, "backed_up": False, "path": "/" + n}
    if d:
        return {"success": False, "backed_up": False,
                "error": "is a directory"}
    err = _copy_file(src, _m.full(n + ".bak"))
    if err:
        return {"success": False, "backed_up": False, "error": err}
    try:
        evicted = _enforce_cap()
    except Exception:
        evicted = []
    return {"success": True, "backed_up": True, "path": "/" + n,
            "backup": "/" + n + ".bak", "evicted": evicted}


def list_backups():
    """All .bak snapshots oldest-first. Never raises."""
    import fsutil as _m
    try:
        baks = _m.find_suffix(".bak")
    except Exception:
        baks = []
    out = []
    for b in baks:
        try:
            fp = _m.full(b)
            out.append({"path": "/" + b, "size": _m.stat_size(fp),
                        "mtime": _m.stat_mtime(fp)})
        except Exception:
            pass
    for a in range(len(out)):
        for c in range(a + 1, len(out)):
            try:
                if (out[c]["mtime"], out[c]["path"]) < (out[a]["mtime"], out[a]["path"]):
                    out[a], out[c] = out[c], out[a]
            except Exception:
                pass
    return {"success": True, "backups": out, "count": len(out),
            "max_backups": MAX_BACKUPS}


def rollback(path):
    """Restore path.bak over path. Refuses managed paths (same rules as the
    write_file tool) and missing snapshots. Never raises."""
    import fsutil as _m
    n = _m.norm(path)
    if n is None or not n:
        return {"success": False, "error": "invalid path"}
    werr = _m.write_refusal(n)
    if werr:
        return {"success": False, "error": werr}
    bak = _m.full(n + ".bak")
    if _m.is_dir(bak) is not False:
        return {"success": False,
                "error": "no backup for '/%s' (no .bak snapshot - "
                         "write the file first)" % n}
    err = _copy_file(bak, _m.full(n))
    if err:
        return {"success": False, "error": err}
    return {"success": True, "path": "/" + n,
            "size": _m.stat_size(_m.full(n))}


PRUNE_DEFAULT_KEEP = 4


def prune(keep=PRUNE_DEFAULT_KEEP):
    """Delete oldest .bak snapshots, keeping the N newest by (mtime, path).

    keep defaults to 4 (D5 /system prune button). Returns {success, keep,
    kept, pruned[], freed (count), freed_bytes}. Never raises; an
    unparseable keep is an error, unremovable files are skipped."""
    try:
        keep = int(keep)
    except Exception:
        return {"success": False, "error": "keep must be a number"}
    if keep < 0:
        keep = 0
    if keep > 64:
        keep = 64
    import fsutil as _m
    try:
        baks = _m.find_suffix(".bak")
    except Exception:
        baks = []
    info = []
    for b in baks:
        try:
            fp = _m.full(b)
            info.append((_m.stat_mtime(fp), b, _m.stat_size(fp)))
        except Exception:
            pass
    # insertion sort oldest-first (tiny lists, no key-sort)
    for a in range(len(info)):
        for c in range(a + 1, len(info)):
            try:
                if (info[c][0], info[c][1]) < (info[a][0], info[a][1]):
                    info[a], info[c] = info[c], info[a]
            except Exception:
                pass
    import os
    pruned = []
    freed_bytes = 0
    while len(info) > keep:
        try:
            _mt, b, sz = info.pop(0)
        except Exception:
            break
        try:
            os.remove(_m.full(b))
            pruned.append("/" + b)
            try:
                freed_bytes += max(0, int(sz))
            except Exception:
                pass
        except Exception:
            pass  # unremovable: dropped from the count, never fatal
    return {"success": True, "keep": keep, "kept": len(info),
            "pruned": pruned, "freed": len(pruned),
            "freed_bytes": freed_bytes}
