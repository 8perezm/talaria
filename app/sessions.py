# sessions.py — session store: one conversation per file, plus keyword search,
# journey feed and ShareGPT trajectory export.
#
# Storage layout (all under the Hermes-parity data home):
#   opt/data/sessions/<id>.jsonl   one conversation; append-only, 2 lines/turn
#   opt/data/sessions/active.json  {"id": "<id>"} — what the web Chat opens
#   opt/data/activity.jsonl        cron / autonomous events (never a session)
#
# Ids: web sessions are `w<epoch>`; Telegram sessions derive from
# session_key() (`mini_telegram_123`). Storage never derives from a label the
# browser sends without sanitising it first (`_safe_id`).
#
# Web vs Telegram: active.json is a WEB-ONLY pointer. Telegram resolves its
# session from the chat id on every turn, so the poller can never hijack the
# tab a human is looking at.
#
# MicroPython-safe: utf-8 only, plain substring ops (no `re`), line-by-line
# log reads (never f.read() of a whole log), lazy `os` imports, guarded stat
# (missing file = skipped, never crash).
try:
    import ujson as json
except ImportError:
    import json

SESS_DIR = "opt/data/sessions"
ACTIVE_PATH = SESS_DIR + "/active.json"

# Legacy single-log locations. ensure_store() moves these into SESS_DIR once;
# nothing else may write them.
LOG_PATH = "opt/data/chatlog.jsonl"
PREV_PATH = "opt/data/chatlog.prev.jsonl"

ACTIVITY_PATH = "opt/data/activity.jsonl"
ACTIVITY_PREV_PATH = "opt/data/activity.prev.jsonl"

MEM_FILES = (("device", "opt/data/memory.txt"), ("user", "opt/data/user.txt"))
SKILLS_DIR = "opt/data/skills"
PENDING_MEM_PATH = "opt/data/pending_mem.json"
PENDING_SKILLS_DIR = "opt/data/pending_skills"

SEARCH_DEFAULT_LIMIT = 5
SEARCH_MAX_LIMIT = 10
SEARCH_OUTPUT_CAP = 2048  # total JSON bytes for search results
SEARCH_CONTENT_CAP = 400  # per-hit content truncation
SEARCH_NEIGHBOR_CAP = 200  # per-neighbor content truncation
SEARCH_MAX_FILES = 6  # newest sessions scanned per query
SEARCH_MAX_ENTRIES = 600  # hard RAM bound: entries kept while scanning

LIST_DEFAULT_LIMIT = 20
LIST_MAX_LIMIT = 40

TRAJ_MAX_PAIRS = 50
TRAJ_VALUE_CAP = 1500  # matches agent_tools.appendChatLog per-role cap

TITLE_CAP = 72

EXPORT_MAX_CHARS = 400000  # one transcript download; the log itself caps ~320KB


# ---------------------------------------------------------------- primitives

def _now():
    try:
        import time
        return int(time.time())
    except Exception:
        return 0


def _exists(path):
    try:
        import os
        os.stat(path)
        return True
    except Exception:
        return False


def _size(path):
    try:
        import os
        return int(os.stat(path)[6])
    except Exception:
        return 0


def _mtime(path):
    """mtime int, or None when the file is missing (never raises).

    MicroPython os.stat is a tuple; mtime is index 8 (see _fs_stat_mtime).
    """
    try:
        import os
        st = os.stat(path)
        if len(st) > 8:
            return int(st[8])
        return 0
    except Exception:
        return None


def safe_id(raw):
    """Sanitised session id ('w847471143', 'mini_telegram_123'), or ''.

    Lowercase alnum plus '_' and '-', max 48 chars. Anything else is refused
    outright — dots are rejected on purpose so `../` and `x.jsonl` can never
    reach the filesystem, and a legacy turn id (`chatlog.jsonl:0:1:abc`) is
    rejected rather than half-understood.
    """
    try:
        s = str(raw if raw is not None else "").strip().lower()
    except Exception:
        return ""
    if not s or len(s) > 48:
        return ""
    out = []
    for ch in s:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "_" or ch == "-":
            out.append(ch)
        else:
            return ""
    if not out:
        return ""
    if out[0] == "-" or out[0] == "_":
        return ""
    return "".join(out)


def _base(path):
    """Filename part of a device path ('' when unusable)."""
    try:
        p = str(path)
    except Exception:
        return ""
    i = p.rfind("/")
    if i >= 0:
        p = p[i + 1:]
    return p


def _stem(name):
    """`w123.jsonl` -> `w123` ('' when not a session file)."""
    try:
        s = str(name)
    except Exception:
        return ""
    if not s.endswith(".jsonl"):
        return ""
    return s[:-6]


def _path(sid):
    """Device path for a sanitised id (caller must use _safe_id first)."""
    return SESS_DIR + "/" + sid + ".jsonl"


def path_for(raw):
    """Device path for a raw id, or '' when the id is not acceptable."""
    sid = safe_id(raw)
    if not sid:
        return ""
    return _path(sid)


def _mkdir_store():
    """mkdir -p opt/data/sessions, checking first so the steady state is
    three failed-free stats instead of three caught exceptions per call."""
    try:
        import os
        for d in ("opt", "opt/data", SESS_DIR):
            try:
                os.stat(d)
                continue
            except Exception:
                pass
            try:
                os.mkdir(d)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _write_active(sid):
    """Persist the active id through a temp file + rename (never half-written)."""
    if not sid:
        return False
    _mkdir_store()
    tmp = ACTIVE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(json.dumps({"id": sid}))
        try:
            import os
            try:
                os.remove(ACTIVE_PATH)
            except Exception:
                pass
            os.rename(tmp, ACTIVE_PATH)
        except Exception:
            # rename unsupported: the plain write is already complete
            pass
        return True
    except Exception:
        try:
            import os
            os.remove(tmp)
        except Exception:
            pass
        return False


def _read_active():
    try:
        with open(ACTIVE_PATH, "r") as f:
            d = json.loads(f.read())
        if isinstance(d, dict):
            return safe_id(d.get("id"))
    except Exception:
        pass
    return ""


def _unique_id(base):
    """`base`, or base-2/base-3... when a session file already exists."""
    sid = safe_id(base) or "w0"
    if not _exists(_path(sid)):
        return sid
    i = 2
    while i < 100:
        cand = safe_id("%s-%d" % (sid, i))
        if cand and not _exists(_path(cand)):
            return cand
        i += 1
    return sid


# ------------------------------------------------------------ store lifecycle

def ensure_store():
    """mkdir the store, migrate legacy logs, guarantee an active session.

    Idempotent and cheap when already migrated (two failed stats). Called from
    initAgentFS() and from every store reader, so a board that upgrades from
    the single-log layout finds its conversation in the new list rather than
    an empty one.
    """
    _mkdir_store()
    _migrate_legacy()
    sid = _read_active()
    if not sid:
        sid = _latest_existing()
        if not sid:
            sid = _unique_id("w%d" % _now())
        _write_active(sid)
    return sid


def _latest_existing():
    """Newest session id by mtime, or '' (no files)."""
    try:
        import os
        names = os.listdir(SESS_DIR)
    except Exception:
        return ""
    best = ""
    best_m = -1
    for fn in names:
        try:
            if isinstance(fn, bytes):
                fn = fn.decode()
        except Exception:
            continue
        sid = safe_id(_stem(fn))
        if not sid:
            continue
        m = _mtime(_path(sid))
        if m is not None and m >= best_m:
            best_m = m
            best = sid
    return best


def _migrate_legacy():
    """Move chatlog.jsonl / .prev into SESS_DIR once. Never raises."""
    try:
        if not _exists(LOG_PATH) and not _exists(PREV_PATH):
            return
        # Oldest first so list ordering and the fallback active id stay sane.
        for src, fallback_off in ((PREV_PATH, -1), (LOG_PATH, 0)):
            if not _exists(src):
                continue
            m = _mtime(src)
            if m is None:
                m = _now()
            sid = _unique_id("w%d" % (int(m) + fallback_off))
            dst = _path(sid)
            try:
                import os
                os.rename(src, dst)
            except Exception:
                # Cross-device / rename refused: copy line by line, then drop.
                try:
                    _copy_lines(src, dst)
                    try:
                        import os as _os2
                        _os2.remove(src)
                    except Exception:
                        pass
                except Exception:
                    continue
            print("[sessions] migrated %s -> %s" % (src, dst))
        if not _read_active():
            sid = _latest_existing()
            if sid:
                _write_active(sid)
    except Exception as e:
        print("[sessions] migration skipped:", str(e)[:80])


def _copy_lines(src, dst):
    with open(src, "r") as f:
        with open(dst, "w") as g:
            for line in f:
                g.write(line)
    return True


def new_session(kind="web", avoid=None):
    """Create a fresh session id, make it active, return it.

    No file is created until the first turn is appended, so pressing New Chat
    repeatedly does not litter the store with empty conversations. `avoid`
    stops an immediately-deleted id from being handed straight back (same
    second, so the timestamp base would otherwise match).
    """
    ensure_store()
    base = "w%d" % _now() if kind == "web" else safe_id(kind) + "_" + str(_now())
    sid = _unique_id(base)
    if avoid and sid == avoid:
        sid = _unique_id(base + "-2")
    _write_active(sid)
    return sid


def active_id(create=True):
    """Current web session id (create + persist one when missing)."""
    sid = ensure_store()
    if sid or not create:
        return sid
    return new_session()


def active_path():
    return _path(active_id())


def set_active(raw):
    """Make an existing/blank session the web pointer. '' when refused."""
    sid = safe_id(raw)
    if not sid:
        return ""
    _mkdir_store()
    _write_active(sid)
    return sid


def id_from_key(key):
    """Flatten a session_key() label into a filesystem-safe session id."""
    flat = []
    for ch in str(key if key is not None else ""):
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "_" or ch == "-":
            flat.append(ch)
        else:
            flat.append("_")
    sid = safe_id("".join(flat))
    return sid or "mini_web_default"


def session_id_for(platform, chat_id):
    """Stable session id for a chat surface (Telegram uses this).

    session_key() is the Hermes-compat label (`mini:telegram:123`); the id is
    the same string with ':' flattened, so the gateway busy-guard and the
    storage key stay in agreement.
    """
    try:
        key = session_key(platform, chat_id)
    except Exception:
        key = "mini:web:default"
    return id_from_key(key)


def _kind_of(sid):
    if sid.startswith("mini_telegram_"):
        return "telegram"
    return "web"


def session_key(platform, chat_id):
    """Session key `mini:{platform}:{chat_id}`. Web chat = `mini:web:default`.

    Hermes builds `agent:{ns}:{platform}:{chat_type}:{chat_id}` via
    build_session_key(): ns isolates profiles (-p), chat_type isolates threads.
    Mini drops both: single profile, no threads.
    """
    try:
        p = str(platform if platform is not None else "web").strip().lower()
    except Exception:
        p = "web"
    if not p:
        p = "web"
    try:
        c = str(chat_id if chat_id is not None else "default").strip()
    except Exception:
        c = "default"
    if not c:
        c = "default"
    # Keep the key parseable on ":" — flatten separators without `re`.
    cp = []
    for ch in p:
        if ch in (":", "/", "\\", " ", "\t", "\n", "\r"):
            cp.append("_")
        else:
            cp.append(ch)
    cc = []
    for ch in c:
        if ch in (":", "/", "\\", " ", "\t", "\n", "\r"):
            cc.append("_")
        else:
            cc.append(ch)
    ps = "".join(cp)[:64] or "web"
    cs = "".join(cc)[:64] or "default"
    return "mini:" + ps + ":" + cs


# ------------------------------------------------------------------- listing

def _first_user_line(path):
    """First user message content in path (title), or ''."""
    try:
        f = open(path, "r")
    except Exception:
        return ""
    try:
        for line in f:
            try:
                s = line.strip()
            except Exception:
                continue
            if not s:
                continue
            pc = _parse_line(s)
            if pc is None:
                continue
            if pc[0] != "user":
                continue
            return pc[1][:TITLE_CAP]
    except Exception:
        return ""
    finally:
        try:
            f.close()
        except Exception:
            pass
    return ""


def list_sessions(limit=LIST_DEFAULT_LIMIT):
    """Newest-first session list for the Sessions page.

    One `os.listdir` + one stat per file; the title costs one open+first-line
    read. Callers must keep this to a single request (the client gate is
    MAX_CONCURRENT=1), hence the hard cap.
    """
    try:
        lim = int(limit)
    except Exception:
        lim = LIST_DEFAULT_LIMIT
    if lim < 1:
        lim = 1
    if lim > LIST_MAX_LIMIT:
        lim = LIST_MAX_LIMIT
    ensure_store()
    active = _read_active()
    rows = []
    try:
        import os
        names = os.listdir(SESS_DIR)
    except Exception:
        names = []
    for fn in names:
        try:
            if isinstance(fn, bytes):
                fn = fn.decode()
        except Exception:
            continue
        sid = safe_id(_stem(fn))
        if not sid:
            continue
        p = _path(sid)
        m = _mtime(p)
        if m is None:
            continue
        title = _first_user_line(p)
        rows.append({"id": sid, "title": title, "created": m,
                     "bytes": _size(p), "kind": _kind_of(sid),
                     "active": sid == active,
                     "empty": not title})
    # Newest first (insertion sort — tiny lists, no key-sort dependency).
    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            try:
                if rows[b]["created"] > rows[a]["created"]:
                    rows[a], rows[b] = rows[b], rows[a]
            except Exception:
                pass
    total = len(rows)
    # The active session always stays visible, even when it is old.
    if len(rows) > lim:
        kept = rows[:lim]
        have = False
        for r in kept:
            if r["id"] == active:
                have = True
                break
        if not have:
            for r in rows:
                if r["id"] == active:
                    kept.append(r)
                    break
        rows = kept
    return {"success": True, "sessions": rows, "count": len(rows),
            "total": total, "active": active}


def delete_session(raw):
    """Delete one conversation file. Deleting the active one starts a new one.

    Refuses anything that is not a sanitised session id (this is also what
    makes the old turn ids fail loudly rather than deleting a file).
    """
    sid = safe_id(raw)
    if not sid:
        return {"success": False, "error": "invalid session id"}
    p = _path(sid)
    if not _exists(p):
        return {"success": False, "error": "session not found (reload the page)"}
    try:
        import os
        os.remove(p)
    except Exception as e:
        return {"success": False, "error": "delete failed: %s" % str(e)[:80]}
    was_active = (_read_active() == sid)
    out = {"success": True, "deleted": sid, "was_active": was_active}
    if was_active:
        out["active"] = new_session(avoid=sid)
    else:
        out["active"] = _read_active()
    return out


# -------------------------------------------------------------------- reading

def _parse_line(line):
    """(role, content) or None. Skips corrupt lines / wrong shapes."""
    try:
        d = json.loads(line)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    try:
        r = str(d.get("r", ""))
        c = str(d.get("c", ""))
    except Exception:
        return None
    if r not in ("user", "assistant") or not c:
        return None
    return r, c[:TRAJ_VALUE_CAP]


def _read_entries(path):
    """[{role, content, line}] for one log file, line by line.

    `line` is the 0-based physical line number (blank/corrupt lines counted).
    Missing files / corrupt lines are skipped. Content pre-truncated to the
    log cap.
    """
    entries = []
    try:
        f = open(path, "r")
    except Exception:
        return entries
    try:
        ln = 0
        for line in f:
            ln += 1
            try:
                s = line.strip()
            except Exception:
                continue
            if not s:
                continue
            pc = _parse_line(s)
            if pc is None:
                continue
            entries.append({"role": pc[0], "content": pc[1],
                            "line": ln - 1})
    except Exception:
        pass
    try:
        f.close()
    except Exception:
        pass
    return entries


def _session_files():
    """Session ids, newest first, capped at SEARCH_MAX_FILES."""
    try:
        import os
        names = os.listdir(SESS_DIR)
    except Exception:
        return []
    rows = []
    for fn in names:
        try:
            if isinstance(fn, bytes):
                fn = fn.decode()
        except Exception:
            continue
        sid = safe_id(_stem(fn))
        if not sid:
            continue
        m = _mtime(_path(sid))
        if m is None:
            continue
        rows.append((m, sid))
    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            if rows[b][0] > rows[a][0]:
                rows[a], rows[b] = rows[b], rows[a]
    out = []
    for m, sid in rows:
        out.append(sid)
        if len(out) >= SEARCH_MAX_FILES:
            break
    return out


def _parse_line_full(line):
    """(role, content) with the full message body — export must not truncate.

    _parse_line() caps content at TRAJ_VALUE_CAP for the ShareGPT export; a
    human reading a downloaded transcript expects the whole answer.
    """
    try:
        d = json.loads(line)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    try:
        r = str(d.get("r", ""))
        c = str(d.get("c", ""))
    except Exception:
        return None
    if r not in ("user", "assistant") or not c:
        return None
    return r, c


def export_text(raw):
    """Plain-text transcript for one conversation (whole file, RAM-bounded).

    Reads line by line and stops once EXPORT_MAX_CHARS is reached, so a 1 MB
    log cannot allocate a 1 MB string on top of the entries. Returns
    {"success": True, id, title, text, messages, truncated} or
    {"success": False, error}.
    """
    sid = safe_id(raw)
    if not sid:
        return {"success": False, "error": "invalid session id"}
    p = _path(sid)
    if not _exists(p):
        return {"success": False, "error": "session not found (reload the page)"}
    title = _first_user_line(p)
    parts = ["talaria agent — conversation %s" % sid]
    if title:
        parts.append("Title: %s" % title.replace("\n", " ").replace("\r", " "))
    parts.append("")
    used = 0
    messages = 0
    truncated = False
    try:
        f = open(p, "r")
    except Exception as e:
        return {"success": False, "error": "read failed: %s" % str(e)[:80]}
    try:
        for line in f:
            try:
                s = line.strip()
            except Exception:
                continue
            if not s:
                continue
            pc = _parse_line_full(s)
            if pc is None:
                continue
            role = "USER" if pc[0] == "user" else "AGENT"
            chunk = "%s: %s" % (role, pc[1])
            if used + len(chunk) > EXPORT_MAX_CHARS:
                truncated = True
                break
            used += len(chunk)
            parts.append(chunk)
            parts.append("")
            messages += 1
    except Exception as e:
        return {"success": False, "error": "read failed: %s" % str(e)[:80]}
    finally:
        try:
            f.close()
        except Exception:
            pass
    if truncated:
        parts.append("[export truncated at %d characters]" % EXPORT_MAX_CHARS)
    return {"success": True, "id": sid, "title": title, "text": "\n".join(parts),
            "messages": messages, "truncated": truncated}


def read_turns(raw, max_pairs=TRAJ_MAX_PAIRS):
    """Chronological turns for one session: [{human, agent, index}].

    Adjacent user→assistant lines pair up, same as trajectory(). A trailing
    user line with no reply yet is included (the page renders it as pending).
    Missing/unknown ids return an empty list rather than an error.
    """
    sid = safe_id(raw)
    if not sid:
        return {"success": False, "error": "invalid session id", "turns": []}
    try:
        mp = int(max_pairs)
    except Exception:
        mp = TRAJ_MAX_PAIRS
    if mp < 1:
        mp = 1
    if mp > TRAJ_MAX_PAIRS:
        mp = TRAJ_MAX_PAIRS
    entries = _read_entries(_path(sid))
    out = []
    i = 0
    n = len(entries)
    while i < n:
        e = entries[i]
        if e.get("role") == "user":
            if i + 1 < n and entries[i + 1].get("role") == "assistant":
                out.append({"human": e.get("content", ""),
                            "agent": entries[i + 1].get("content", "")})
                i += 2
                continue
            if i + 1 == n:
                out.append({"human": e.get("content", ""), "agent": ""})
        i += 1
    truncated = False
    if len(out) > mp:
        out = out[len(out) - mp:]
        truncated = True
    for k in range(len(out)):
        out[k]["index"] = k + 1
    return {"success": True, "id": sid, "turns": out, "count": len(out),
            "truncated": truncated}


def search(query, limit=SEARCH_DEFAULT_LIMIT):
    """Keyword scan over the newest sessions.

    Case-insensitive AND-of-words: every query word must occur in the entry;
    ranked by total hit count, recency (later = better) breaking ties. Each
    hit carries its ±1 adjacent entries (prev/next single log lines). Total
    JSON output is capped at ~2KB (lowest-ranked hits dropped first).

    NOTE: agent_tools.injectRecentLog is intentionally unchanged — it still
    injects the last-8 of the ACTIVE session only. This search is the
    cross-session recall path (finds facts from other conversations).
    """
    try:
        q = str(query if query is not None else "").strip()
    except Exception:
        return {"success": False, "error": "query required"}
    if not q:
        return {"success": False, "error": "query required"}
    try:
        lim = int(limit)
    except Exception:
        lim = SEARCH_DEFAULT_LIMIT
    if lim < 1:
        lim = 1
    if lim > SEARCH_MAX_LIMIT:
        lim = SEARCH_MAX_LIMIT
    words = _words(q)
    if not words:
        return {"success": False, "error": "query has no searchable words"}
    ensure_store()
    entries = []
    for sid in _session_files():
        for e in _read_entries(_path(sid)):
            e["source"] = _path(sid)
            e["pos"] = len(entries)
            entries.append(e)
            if len(entries) >= SEARCH_MAX_ENTRIES:
                break
        if len(entries) >= SEARCH_MAX_ENTRIES:
            break
    scored = []  # (score, pos)
    for pos, e in enumerate(entries):
        try:
            low = e["content"].lower()
        except Exception:
            continue
        ok = True
        for w in words:
            if w not in low:
                ok = False
                break
        if not ok:
            continue
        s = 0
        for w in words:
            try:
                s += low.count(w)
            except Exception:
                s += 1
        scored.append((s, pos))
    # Best first: score desc, recency (pos) desc. Insertion sort — tiny lists,
    # no key-sort dependency (same style as memory.py/skillstore.py).
    for a in range(len(scored)):
        for b in range(a + 1, len(scored)):
            sa, pa = scored[a]
            sb, pb = scored[b]
            if sb > sa or (sb == sa and pb > pa):
                scored[a], scored[b] = scored[b], scored[a]
    results = []
    for s, pos in scored[:lim]:
        e = entries[pos]
        item = {"role": e["role"],
                "content": e["content"][:SEARCH_CONTENT_CAP],
                "score": s, "source": e["source"], "pos": pos}
        if pos > 0:
            pe = entries[pos - 1]
            item["prev"] = {"role": pe["role"],
                            "content": pe["content"][:SEARCH_NEIGHBOR_CAP]}
        else:
            item["prev"] = None
        if pos + 1 < len(entries):
            ne = entries[pos + 1]
            item["next"] = {"role": ne["role"],
                            "content": ne["content"][:SEARCH_NEIGHBOR_CAP]}
        else:
            item["next"] = None
        results.append(item)
    # Cap total output ~2KB: drop lowest-ranked hits first.
    try:
        while results and len(json.dumps(results)) > SEARCH_OUTPUT_CAP:
            results = results[:-1]
    except Exception:
        pass
    return {"success": True, "query": q, "results": results,
            "count": len(results)}


def _words(s):
    """Lowercase alphanumeric tokens without `re` (same as memory.py)."""
    out = []
    cur = []
    for ch in str(s).lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out


# ------------------------------------------------------------------- journey

def journey():
    """Time-ordered feed of learning/lifecycle events, mtime ascending.

    Sources: memory.txt/user.txt (mtime+size+usage%), each skills/*.md
    (mtime+size), pending counts (pending_mem.json count, pending_skills/
    count), each session log + activity log. Missing files are skipped.
    """
    events = []
    # --- curated memories ---
    for target, path in MEM_FILES:
        m = _mtime(path)
        if m is None:
            continue
        usage_s = ""
        pct = 0
        try:
            import memory as _mem
            p, n, cap = _mem.usage(target)
            pct = int(p)
            usage_s = "%d%% %d/%d chars" % (pct, int(n), int(cap))
        except Exception:
            pass
        events.append({"kind": "memory", "name": path, "target": target,
                       "mtime": m, "size": _size(path),
                       "usage": usage_s, "usage_pct": pct})
    # --- skills ---
    try:
        import os
        try:
            files = os.listdir(SKILLS_DIR)
        except Exception:
            files = []
        for fn in files:
            try:
                if isinstance(fn, bytes):
                    fn = fn.decode()
            except Exception:
                continue
            if not fn.endswith(".md"):
                continue
            fp = SKILLS_DIR + "/" + fn
            m = _mtime(fp)
            if m is None:
                continue
            base = fn[:-3]
            events.append({"kind": "skill", "name": base, "path": fp,
                           "mtime": m, "size": _size(fp)})
    except Exception:
        pass
    # --- pending queues (always reported, even when empty) ---
    try:
        import memory as _mem2
        pcount = len(_mem2.list_pending())
    except Exception:
        pcount = 0
    pm = _mtime(PENDING_MEM_PATH)
    events.append({"kind": "pending", "name": PENDING_MEM_PATH,
                   "count": pcount, "mtime": pm if pm is not None else 0,
                   "size": _size(PENDING_MEM_PATH)})
    scount = 0
    smax = 0
    try:
        import skillstore as _sk
        try:
            scount = len(_sk.list_pending())
        except Exception:
            scount = 0
    except Exception:
        pass
    try:
        import os
        try:
            pfiles = os.listdir(PENDING_SKILLS_DIR)
        except Exception:
            pfiles = []
        for fn in pfiles:
            try:
                if isinstance(fn, bytes):
                    fn = fn.decode()
            except Exception:
                continue
            if not fn.endswith(".json"):
                continue
            m = _mtime(PENDING_SKILLS_DIR + "/" + fn)
            if m is not None and m > smax:
                smax = m
        if not pfiles:
            try:
                dm = _mtime(PENDING_SKILLS_DIR)
                if dm is not None:
                    smax = dm
            except Exception:
                pass
    except Exception:
        pass
    events.append({"kind": "pending", "name": PENDING_SKILLS_DIR,
                   "count": scount, "mtime": smax})
    # --- session logs + activity ---
    ensure_store()
    for sid in _session_files():
        p = _path(sid)
        m = _mtime(p)
        if m is None:
            continue
        events.append({"kind": "log", "name": p, "session": sid,
                       "mtime": m, "size": _size(p)})
    for path in (ACTIVITY_PATH, ACTIVITY_PREV_PATH):
        m = _mtime(path)
        if m is None:
            continue
        events.append({"kind": "log", "name": path, "session": "",
                       "mtime": m, "size": _size(path)})
    # Sort by mtime ascending (insertion sort — tiny lists, no key-sort dep).
    for a in range(len(events)):
        for b in range(a + 1, len(events)):
            try:
                ma = int(events[a].get("mtime", 0))
            except Exception:
                ma = 0
            try:
                mb = int(events[b].get("mtime", 0))
            except Exception:
                mb = 0
            if mb < ma:
                events[a], events[b] = events[b], events[a]
    return {"success": True, "events": events, "count": len(events)}


# ---------------------------------------------------------------- trajectory

def trajectory(max_pairs=TRAJ_MAX_PAIRS):
    """ShareGPT export across every session, oldest first.

    {"conversations": [{"from": "human"|"gpt", "value": ...}]} — one human/gpt
    pair per adjacent user→assistant turn. Unpaired turns are skipped. Capped
    at 50 pairs (most recent win, still time-ordered); values truncated to the
    1500-char log cap, same as agent_tools.appendChatLog.
    """
    try:
        mp = int(max_pairs)
    except Exception:
        mp = TRAJ_MAX_PAIRS
    if mp < 1:
        mp = 1
    if mp > TRAJ_MAX_PAIRS:
        mp = TRAJ_MAX_PAIRS
    ensure_store()
    ids = _session_files()
    ids.reverse()  # oldest first
    pairs = []
    for sid in ids:
        entries = _read_entries(_path(sid))
        i = 0
        n = len(entries)
        while i < n:
            e = entries[i]
            if e.get("role") == "user":
                if i + 1 < n and entries[i + 1].get("role") == "assistant":
                    pairs.append((e.get("content", "")[:TRAJ_VALUE_CAP],
                                  entries[i + 1].get("content", "")[:TRAJ_VALUE_CAP]))
                    i += 2
                    continue
            i += 1
    truncated = False
    if len(pairs) > mp:
        pairs = pairs[len(pairs) - mp:]
        truncated = True
    conv = []
    for u, a in pairs:
        conv.append({"from": "human", "value": u})
        conv.append({"from": "gpt", "value": a})
    return {"success": True, "conversations": conv,
            "pairs": len(pairs), "truncated": truncated}
