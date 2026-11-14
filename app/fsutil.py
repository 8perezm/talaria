# fsutil.py — canonical filesystem helpers (Mini Hermes Phase 7).
# server.py's _fs_* wrappers, the file tools (read_file / write_file /
# patch_file / search_files) and checkpoint.py ALL share this module — one
# implementation, no duplication. MicroPython-safe: os.listdir/os.stat only,
# utf-8 only, chunked I/O, plain substring ops (no `re`), bounded outputs,
# lazy `os` imports. _FS_ROOT lets host tests point the tree at a tmp dir;
# on device it stays "".
try:
    import ujson as json  # noqa: F401 (kept for symmetry with sister modules)
except ImportError:
    import json  # noqa: F401

_FS_ROOT = ""
FS_MAX_READ = 100000
FS_MAX_WRITE = 200000


def read_jsonl_tail(path, max_lines=10, block_bytes=16384):
    """Last max_lines parseable JSON objects from a JSONL file, oldest first.

    Reads backwards in fixed-size blocks, so RAM/time scale with the requested
    tail rather than the file size (matters for a big chat log, or one moved to
    USB storage later). A line split across blocks is never parsed half-way.
    Returns (objects, file_bytes).
    """
    import os
    try:
        total = int(os.stat(path)[6])
    except Exception:
        return [], 0
    if total <= 0:
        return [], total
    want = int(max_lines)
    if want < 1:
        want = 1
    found = []      # newest first until the final reverse
    carry = b""     # partial line at the start of the latest block
    pos = total
    try:
        with open(path, "rb") as f:
            while pos > 0 and len(found) < want:
                n = block_bytes if pos > block_bytes else pos
                pos -= n
                f.seek(pos)
                chunk = f.read(n)
                if not chunk:
                    break
                lines = (chunk + carry).split(b"\n")
                if pos > 0:
                    # lines[0] may be cut mid-line; join it to the next block.
                    carry = lines[0]
                    lines = lines[1:]
                else:
                    carry = b""
                i = len(lines) - 1
                while i >= 0 and len(found) < want:
                    raw = lines[i]
                    i -= 1
                    try:
                        e = json.loads(raw.strip().decode("utf-8"))
                    except Exception:
                        continue
                    if isinstance(e, dict):
                        found.append(e)
    except OSError:
        return [], total
    found.reverse()
    return found, total

# File-tool budgets (the 100KB/200KB Explorer caps do NOT apply to the tools;
# small bounded caps keep tool results fittable in one turn).
TOOL_CONTENT_MAX = 4096  # one tool call's payload (model output budget)
TOOL_FILE_MAX = 16384    # assembled file cap for write_file append / patch
READ_SLICE_DEFAULT = 4096
READ_SLICE_MAX = 4096
CHUNK = 2048  # copy/skip chunk (single-pass, low RAM)

# search_files budgets.
SEARCH_MAX_HITS = 20
SEARCH_MAX_FILE_BYTES = 32768  # bigger files are skipped, never half-read
SEARCH_MAX_FILES = 200
SEARCH_MAX_DIRS = 64
SEARCH_SNIPPET_MAX = 160
SEARCH_PATTERN_MAX = 120
SEARCH_LINE_MAX = 1024  # longer lines are truncated before matching

# Managed user-data home (Hermes parity: the dashboard's Files root).
# System code stays at flash `/`; everything the user owns lives under here.
# Files (`/api/files`) is locked to this subtree; system edits go through
# the separate `/api/system/files/*` repair hatch.
DATA_ROOT = "opt/data"
DATA_WORKSPACE = "opt/data/workspace"

# Legacy flat locations (pre-split boards kept these at flash root).
# ensure_data_tree() renames each one into DATA_ROOT once, when the new
# path is still missing. New code must use the DATA_* paths only.
_LEGACY_DATA_FILES = ("memory.txt", "user.txt", "chatlog.jsonl",
                       "chatlog.prev.jsonl", "cron.json", "tg.json",
                       "bundles.json", "pending_mem.json")
_LEGACY_DATA_DIRS = ("skills", "pending_skills")

# Secrets / partial writes: never handed to the model.
_READ_REFUSED_NAMES = ("config.yaml", "config.json", "config.json.bak", "tg.json")

# Managed state: the tools must not write these directly (dedicated
# tool/API flows own them); the Explorer UI keeps its historic behavior.
_WRITE_REFUSED_NAMES = ("config.yaml", "config.json", "config.json.bak",
                        "memory.txt", "user.txt",
                        "chatlog.jsonl", "chatlog.prev.jsonl", "cron.json",
                        "tg.json", "bundles.json", "pending_mem.json",
                        "active.json", "activity.jsonl", "activity.prev.jsonl")
_WRITE_REFUSED_DIRS = ("skills", "pending_skills", DATA_ROOT + "/sessions")


def _base(norm):
    try:
        return norm.rsplit("/", 1)[-1] if norm else ""
    except Exception:
        return ""


def norm(p):
    """Normalise a user-supplied path to 'a/b/c' ('' = root). None = invalid."""
    if p is None:
        return ""
    s = str(p).replace("\\", "/").strip()
    if not s or s == "/":
        return ""
    parts = []
    for seg in s.split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            return None
        if "\x00" in seg:
            return None
        parts.append(seg)
        if len(parts) > 32:
            return None
    out = "/".join(parts)
    if len(out) > 200:
        return None
    return out


def full(n, root=None):
    base = (root if root is not None else _FS_ROOT) or ""
    base = base.rstrip("/")
    if base:
        return base if not n else base + "/" + n
    return "/" + n if n else "/"


def tool_path(n):
    """Resolve a file-tool path for the workspace script convention.

    - 'workspace/x' and 'workspace/x.py' map to opt/data/workspace/x(.py).
    - A bare 'x.py' maps to the workspace only when no root file of that
      name exists. New scripts therefore land where run_script looks, while
      repairs to root entry points (main.py, boot.py) still address the root.
    - Everything else (app/..., www/..., non-.py bare names) is unchanged.
    """
    if not n:
        return n
    if n == "workspace":
        return DATA_WORKSPACE
    if n.startswith("workspace/"):
        return DATA_WORKSPACE + n[len("workspace"):]
    if "/" not in n and n.endswith(".py") and is_dir(full(n)) is None:
        return DATA_WORKSPACE + "/" + n
    return n


def parent(n):
    if not n or "/" not in n:
        return ""
    return n.rsplit("/", 1)[0]


def under_data(n):
    """True when norm n is the data home itself or inside it."""
    try:
        return n == DATA_ROOT or (n.startswith(DATA_ROOT + "/") if n else False)
    except Exception:
        return False


def to_data(n):
    """Map a Files-API norm into the data home.

    '' (root listing) -> DATA_ROOT; an already-data path passes through;
    anything else is treated as relative to the data home, so system
    paths can never be addressed through the locked endpoint.
    Returns None for invalid input.
    """
    if n is None:
        return None
    try:
        if not n:
            return DATA_ROOT
        if under_data(n):
            return n
        return DATA_ROOT + "/" + n
    except Exception:
        return None


def ensure_data_tree(root=None):
    """mkdir -p opt/data + opt/data/workspace; one-time legacy migration.

    Moves pre-split root files/dirs (memory.txt, skills/, ...) into DATA_ROOT
    when the new path is still missing. Best-effort, never raises: a
    half-migrated board keeps working on the next boot. Creates both the
    relative chain (CWD-relative: device `/`, host tests chdir tmp) and the
    _FS_ROOT-absolute chain (host tests that override _FS_ROOT without
    chdir), so direct `open("opt/data/...")` writers work everywhere.
    Returns '' (err text unused — kept for symmetry with ensure_parent).
    """
    import os
    base = (root if root is not None else _FS_ROOT) or ""
    for d in ("opt", DATA_ROOT, DATA_WORKSPACE, DATA_ROOT + "/sessions"):
        # relative (CWD): device + chdir-style tests
        try:
            os.mkdir(d)
        except Exception:
            pass
        # absolute via _FS_ROOT: tests that only override _FS_ROOT
        try:
            fp = full(d, root)
            if fp != d and fp != "/" + d:
                try:
                    os.mkdir(fp)
                except Exception:
                    pass
        except Exception:
            pass
        # os.makedirs fallback for deeply-missing parents (host only;
        # MicroPython has no makedirs — the per-segment loop above covers it).
        try:
            _mk = getattr(os, "makedirs", None)
            if _mk is not None:
                try:
                    _mk(d, exist_ok=True)
                except Exception:
                    pass
                if base:
                    try:
                        _mk(full(d, root), exist_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass
    for name in _LEGACY_DATA_FILES:
        for src, dst in ((name, DATA_ROOT + "/" + name),
                         (full(name, root), full(DATA_ROOT + "/" + name, root))):
            try:
                if is_dir(src) is False and is_dir(dst) is None:
                    try:
                        os.rename(src, dst)
                        break
                    except Exception:
                        pass
            except Exception:
                pass
    for name in _LEGACY_DATA_DIRS:
        for src, dst in ((name, DATA_ROOT + "/" + name),
                         (full(name, root), full(DATA_ROOT + "/" + name, root))):
            try:
                if is_dir(src) is True and is_dir(dst) is None:
                    try:
                        os.rename(src, dst)
                        break
                    except Exception:
                        pass
            except Exception:
                pass
    return ""


def is_dir(fp):
    import os
    try:
        st = os.stat(fp)
    except Exception:
        return None
    try:
        mode = st[0]
    except Exception:
        return None
    try:
        import stat as _stat
        return _stat.S_ISDIR(mode)
    except Exception:
        pass
    return bool(mode & 0x4000)


def stat_size(fp):
    import os
    try:
        return int(os.stat(fp)[6])
    except Exception:
        return 0


def stat_mtime(fp):
    import os
    try:
        st = os.stat(fp)
        if len(st) > 8:
            return int(st[8])
    except Exception:
        pass
    return 0


def list_dir(n, root=None):
    """Return (entries, err). entries=[{name,path,is_dir,size,mtime}].

    A directory listing is the most-hit filesystem call in the dashboard, and
    littlefs stats are expensive: the old version did three `os.stat` calls
    per entry (is_dir + size + mtime), which turned a 33-entry root into a
    ~9 s request. `os.ilistdir` already reports type and size, so this does at
    most one stat per entry and only for the mtime.
    """
    import os
    fp = full(n, root)
    if is_dir(fp) is not True and n != "":
        # root always listable; anything else must be a dir
        if is_dir(fp) is None:
            return None, "not found"
        return None, "not a directory"
    names = []
    try:
        il = getattr(os, "ilistdir", None)
        if il is not None:
            for e in il(fp):
                try:
                    name = e[0]
                except Exception:
                    continue
                if isinstance(name, bytes):
                    try:
                        name = name.decode()
                    except Exception:
                        continue
                if not name or name in (".", ".."):
                    continue
                kind = 0
                size = -1
                try:
                    if len(e) > 1:
                        kind = int(e[1])
                    if len(e) > 3:
                        size = int(e[3])
                except Exception:
                    pass
                names.append((name, kind, size))
        else:
            for name in os.listdir(fp):
                if isinstance(name, bytes):
                    try:
                        name = name.decode()
                    except Exception:
                        continue
                if not name or name in (".", ".."):
                    continue
                names.append((name, 0, -1))
    except Exception as e:
        return None, "list failed: %s" % str(e)[:80]
    try:
        names.sort(key=lambda t: t[0].lower())
    except Exception:
        names.sort()

    entries = []
    for name, kind, size_hint in names[:500]:
        child = (n + "/" + name) if n else name
        ff = full(child, root)
        isd = bool(kind & 0x4000)
        size = 0 if isd else (size_hint if size_hint > 0 else 0)
        mtime = 0
        try:
            st = os.stat(ff)
            try:
                isd = bool(int(st[0]) & 0x4000)
            except Exception:
                pass
            if not isd:
                try:
                    size = int(st[6])
                except Exception:
                    pass
            try:
                if len(st) > 8:
                    mtime = int(st[8])
            except Exception:
                pass
        except Exception:
            pass
        entries.append({"name": name, "path": "/" + child, "is_dir": isd,
                        "size": size, "mtime": mtime})
    return entries, ""


def read_text(n, max_bytes=FS_MAX_READ, root=None):
    fp = full(n, root)
    d = is_dir(fp)
    if d is None:
        return None, "not found", 0
    if d:
        return None, "is a directory", 0
    size = stat_size(fp)
    try:
        with open(fp, "rb") as f:
            try:
                data = f.read(max_bytes + 1)
            except TypeError:
                data = f.read()  # very old MicroPython read() takes no size
    except Exception as e:
        return None, "read failed: %s" % str(e)[:80], 0
    trunc = len(data) > max_bytes
    if trunc:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8")
    except Exception:
        return None, "binary file (download instead)", size
    return {"content": text, "size": size, "truncated": trunc}, "", size


def read_slice(n, offset=0, limit=READ_SLICE_DEFAULT, root=None):
    """(result, err, size): content slice [offset:offset+limit]. Single pass
    in 2KB chunks — never holds more than limit+chunk in RAM."""
    try:
        off = int(offset)
    except Exception:
        return None, "bad offset", 0
    try:
        lim = int(limit)
    except Exception:
        return None, "bad limit", 0
    if off < 0:
        return None, "offset must be >= 0", 0
    if lim < 1:
        return None, "limit must be 1..%d" % READ_SLICE_MAX, 0
    if lim > READ_SLICE_MAX:
        lim = READ_SLICE_MAX
    fp = full(n, root)
    d = is_dir(fp)
    if d is None:
        return None, "not found", 0
    if d:
        return None, "is a directory", 0
    size = stat_size(fp)
    try:
        f = open(fp, "rb")
    except Exception as e:
        return None, "read failed: %s" % str(e)[:80], 0
    try:
        left = off
        while left > 0:
            step = CHUNK if left > CHUNK else left
            chunk = f.read(step)
            if not chunk:
                break
            left -= len(chunk)
        data = f.read(lim + 1)
    except Exception as e:
        try:
            f.close()
        except Exception:
            pass
        return None, "read failed: %s" % str(e)[:80], size
    try:
        f.close()
    except Exception:
        pass
    if data is None:
        data = b""
    trunc = (off > 0) or (len(data) > lim)
    if len(data) > lim:
        data = data[:lim]
    try:
        text = data.decode("utf-8")
    except Exception:
        if b"\x00" in data:
            return None, "binary file (download instead)", size
        # No NUL: a slice that started mid-multibyte-char, not a binary.
        try:
            text = data.decode("utf-8", "ignore")
        except Exception:
            return None, "binary file (download instead)", size
    return {"content": text, "size": size, "truncated": trunc}, "", size


def ensure_parent(n, root=None):
    """mkdir -p the parent chain of n. Returns '' or err text."""
    import os
    par = parent(n)
    if not par:
        return ""
    cur = ""
    for seg in par.split("/"):
        cur = seg if not cur else cur + "/" + seg
        try:
            os.mkdir(full(cur, root))
        except Exception as e:
            # 17 = EEXIST on MicroPython/CPython; anything else on existing
            # dir is also fine — verify it is a dir before giving up.
            if is_dir(full(cur, root)) is not True:
                return "mkdir failed: %s" % str(e)[:80]
    return ""


def write_text(n, content, max_bytes=FS_MAX_WRITE, root=None):
    if not n:
        return "no filename"
    if content is None:
        return "no content"
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except Exception:
            return "binary content not supported here (use upload)"
    data = content.encode("utf-8")
    if len(data) > max_bytes:
        return "file too large (%dB, max %dB)" % (len(data), max_bytes)
    err = ensure_parent(n, root)
    if err:
        return err
    try:
        with open(full(n, root), "wb") as f:
            f.write(data)
    except Exception as e:
        return "write failed: %s" % str(e)[:80]
    return ""


def delete(n, root=None):
    """Delete a file or directory tree. Refuses root. Returns '' or err."""
    import os
    if not n:
        return "refusing to delete /"
    fp = full(n, root)
    d = is_dir(fp)
    if d is None:
        return "not found"
    if not d:
        try:
            os.remove(fp)
        except Exception as e:
            return "delete failed: %s" % str(e)[:80]
        return ""
    # directory: iterative depth-first delete (no os.walk on MicroPython)
    stack = [n]
    order = []
    while stack:
        cur = stack.pop()
        order.append(cur)
        entries, err = list_dir(cur, root)
        if err:
            return err
        for e in entries:
            child = e["path"][1:]  # strip leading '/'
            if e["is_dir"]:
                stack.append(child)
            else:
                try:
                    os.remove(full(child, root))
                except Exception as ex:
                    return "delete failed: %s" % str(ex)[:80]
    for cur in reversed(order):
        try:
            os.rmdir(full(cur, root))
        except Exception as e:
            return "rmdir failed: %s" % str(e)[:80]
    return ""


def walk_files(start, max_dirs=SEARCH_MAX_DIRS, max_files=500, root=None):
    """(file_norms, truncated): iterative pre-order walk under start (a norm
    path, '' = whole tree). Sorted per dir (list_dir order). Never walks
    above start — start itself comes from norm()."""
    files = []
    trunc = False
    stack = [start]
    seen_dirs = 0
    while stack:
        if seen_dirs >= max_dirs:
            trunc = True
            break
        cur = stack.pop()
        seen_dirs += 1
        entries, err = list_dir(cur, root)
        if err:
            continue  # unreadable dir: skip, never fatal
        subs = []
        for e in entries:
            child = e["path"][1:]
            if e["is_dir"]:
                subs.append(child)
            else:
                if len(files) >= max_files:
                    trunc = True
                    break
                files.append(child)
            if trunc:
                break
        if trunc:
            break
        # push reversed so pop() visits in sorted order
        for s in reversed(subs):
            stack.append(s)
    return files, trunc


def find_suffix(suffix, start="", root=None):
    """All file norms under start ending with suffix (for .bak rotation)."""
    files, _ = walk_files(start, SEARCH_MAX_DIRS, 500, root)
    out = []
    for fn in files:
        try:
            if fn.endswith(suffix):
                out.append(fn)
        except Exception:
            pass
    try:
        out.sort()
    except Exception:
        pass
    return out


def grep_files(pattern, root="/", cap=SEARCH_MAX_HITS):
    """Case-insensitive substring search under root (a norm path, ''/None =
    whole tree). Returns a result dict (never raises). Skips binary files
    (NUL byte or undecodable head) and files over SEARCH_MAX_FILE_BYTES.
    Matches: [{file, line, text}] capped at cap (then truncated=True); the
    walk itself is capped (dirs/files) which also sets truncated=True."""
    try:
        pat = str(pattern or "")
    except Exception:
        return {"success": False, "error": "pattern is required"}
    if not pat:
        return {"success": False, "error": "pattern is required"}
    if len(pat) > SEARCH_PATTERN_MAX:
        return {"success": False,
                "error": "pattern too long (%d chars, max %d)"
                         % (len(pat), SEARCH_PATTERN_MAX)}
    try:
        cap = int(cap)
    except Exception:
        cap = SEARCH_MAX_HITS
    if cap < 1:
        cap = 1
    if cap > SEARCH_MAX_HITS:
        cap = SEARCH_MAX_HITS
    start = norm(root if root else "/")
    if start is None:
        return {"success": False,
                "error": "invalid root (never walks above /)"}
    start = tool_path(start)
    disp = "/" + start if start else "/"
    fp0 = full(start)
    d0 = is_dir(fp0)
    if d0 is None:
        return {"success": False, "error": "root not found"}
    if d0:
        files, walk_trunc = walk_files(start, SEARCH_MAX_DIRS,
                                       SEARCH_MAX_FILES)
    else:
        files, walk_trunc = [start], False  # root names one file: scan it
    try:
        plow = pat.lower()
    except Exception:
        plow = pat
    hits = []
    trunc = bool(walk_trunc)
    scanned = 0
    for fn in files:
        if len(hits) >= cap:
            trunc = True
            break
        if scanned >= SEARCH_MAX_FILES:
            trunc = True
            break
        scanned += 1
        fp = full(fn)
        if read_refusal(fn):
            continue  # secrets / partial writes never reach the model
        if stat_size(fp) > SEARCH_MAX_FILE_BYTES:
            continue
        try:
            with open(fp, "rb") as f:
                try:
                    head = f.read(512)
                except TypeError:
                    head = f.read()
        except Exception:
            continue
        if head is None:
            head = b""
        if b"\x00" in head:
            continue  # binary: skip, never fatal
        try:
            head.decode("utf-8")
        except Exception:
            continue  # not utf-8 text: skip
        try:
            f = open(fp, "rb")
        except Exception:
            continue
        lineno = 0
        try:
            for raw in f:
                lineno += 1
                if len(hits) >= cap:
                    break
                if len(raw) > SEARCH_LINE_MAX:
                    raw = raw[:SEARCH_LINE_MAX]
                try:
                    line = raw.decode("utf-8")
                except Exception:
                    break  # mid-file binary: stop this file, keep file out
                try:
                    found = plow in line.lower()
                except Exception:
                    found = False
                if found:
                    try:
                        snip = line.strip()[:SEARCH_SNIPPET_MAX]
                    except Exception:
                        snip = ""
                    hits.append({"file": "/" + fn, "line": lineno,
                                 "text": snip})
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass
    if len(hits) >= cap:
        # cap reached: more matches may exist (same file or later files).
        trunc = True
    return {"success": True, "pattern": pat, "root": disp,
            "matches": hits, "count": len(hits), "truncated": trunc}


def read_refusal(n):
    """Error text when the file tools must not READ n, else ''. Secrets
    (config.yaml/config.json: API key + wifi; tg.json: bot token) and partial
    writes (*.tmp) are refused. Other .bak snapshots ARE readable."""
    b = _base(n)
    if b in _READ_REFUSED_NAMES:
        if b == "tg.json":
            return ("refused: tg.json holds secrets (bot token + allowlist) - "
                    "manage it via the gateway API")
        return ("refused: %s holds secrets (API key + wifi) - manage it via "
                "the Config page or the raw YAML editor" % b)
    if b.endswith(".tmp"):
        return ("refused: '%s' is a partial write (settings land here first) "
                "- nothing readable" % b[:40])
    return ""


def write_refusal(n):
    """Error text when the file tools / rollback must not WRITE n, else ''.
    Managed state owns dedicated flows (named in each message); skills/
    bypass attempts are pointed at the skill_view + /api/skills
    propose/approve flow."""
    if not n:
        return "no filename"
    b = _base(n)
    # One conversation per file, owned by the session store (append-only).
    try:
        if n == DATA_ROOT + "/sessions" or n.startswith(DATA_ROOT + "/sessions/"):
            return ("refused: conversations are managed - use the Sessions "
                    "page (/api/sessions), never direct file writes")
    except Exception:
        pass
    # Managed skill dirs, at the legacy root or under the data home.
    # The workspace (opt/data/workspace/...) stays writable — only the two
    # managed stores are refused.
    _managed_prefixes = ("skills", "pending_skills",
                         DATA_ROOT + "/skills",
                         DATA_ROOT + "/pending_skills")
    for _mp in _managed_prefixes:
        try:
            if n == _mp or n.startswith(_mp + "/"):
                if _mp.endswith("skills") and not _mp.endswith("pending_skills"):
                    return ("refused: skills/ is managed - read with skill_view and "
                            "change skills via the /api/skills propose/approve flow, "
                            "never by direct file writes")
                return ("refused: pending_skills/ holds staged approvals - review via "
                        "/api/skills?pending=1, never by direct file writes")
        except Exception:
            pass
    if b in _WRITE_REFUSED_NAMES or b.startswith("pending_"):
        if b in ("config.yaml", "config.json", "config.json.bak"):
            return ("refused: %s holds secrets - manage it via the Config "
                    "page or the raw YAML editor" % b)
        if b in ("memory.txt", "user.txt"):
            return ("refused: %s is managed - use the memory tool" % b[:20])
        if b.startswith("chatlog") and b.endswith(".jsonl"):
            return ("refused: chat logs are append-only - read via "
                    "session_search, rotate via POST /api/memory "
                    "{clear_log:true}")
        if b in ("activity.jsonl", "activity.prev.jsonl"):
            return ("refused: the activity log is append-only - read via "
                    "/api/journey")
        if b == "active.json":
            return ("refused: active.json is the session pointer - use "
                    "/api/sessions/activate")
        if b == "cron.json":
            return ("refused: cron.json is managed - use the cron tool or "
                    "/api/cron")
        if b == "tg.json":
            return ("refused: tg.json holds secrets - manage it via the "
                    "gateway API")
        if b == "bundles.json":
            return ("refused: bundles.json is managed - use /api/skills")
        return ("refused: '%s' is staged-approval state - review via the "
                "pending queues, never by direct file writes" % b[:40])
    if b.startswith("chatlog") and b.endswith(".jsonl"):
        return ("refused: chat logs are append-only - read via "
                "session_search, rotate via POST /api/memory {clear_log:true}")
    if b.endswith(".tmp") or b.endswith(".bak"):
        return ("refused: '%s' is checkpoint-managed - write the real file, "
                "the .bak/.tmp sidecars follow it" % b[:40])
    return ""
