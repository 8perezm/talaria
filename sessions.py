# sessions.py — Mini Hermes Phase 4: session keys, keyword search, /new rotation,
# journey feed, ShareGPT trajectory export.
# MicroPython-safe: utf-8 only, plain substring ops (no `re`), line-by-line
# log reads (never f.read() of the whole 32KB+16KB logs into multiple copies),
# lazy `os` imports, guarded stat (missing file = skipped, never crash).
try:
    import ujson as json
except ImportError:
    import json

LOG_PATH = "chatlog.jsonl"
PREV_PATH = "chatlog.prev.jsonl"
MEM_FILES = (("device", "memory.txt"), ("user", "user.txt"))
SKILLS_DIR = "skills"
PENDING_MEM_PATH = "pending_mem.json"
PENDING_SKILLS_DIR = "pending_skills"

SEARCH_DEFAULT_LIMIT = 5
SEARCH_MAX_LIMIT = 10
SEARCH_OUTPUT_CAP = 2048  # total JSON bytes for search results
SEARCH_CONTENT_CAP = 400  # per-hit content truncation
SEARCH_NEIGHBOR_CAP = 200  # per-neighbor content truncation

TRAJ_MAX_PAIRS = 50
TRAJ_VALUE_CAP = 1500  # matches agent_tools.appendChatLog per-role cap


def session_key(platform, chat_id):
    """Session key `mini:{platform}:{chat_id}`. Web chat = `mini:web:default`.

    Hermes builds `agent:{ns}:{platform}:{chat_type}:{chat_id}` via
    build_session_key(): ns isolates profiles (-p), chat_type isolates threads.
    Mini drops both: single profile, no threads — one active log + `.prev`.
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


def _load_all():
    """Time-ordered entries across .prev (older) + current log (newer).

    Single pass, line-by-line (no whole-file read into multiple copies).
    Each entry: {role, content, source, pos}. Missing files / corrupt lines
    are skipped. Content pre-truncated to the 1500-char log cap.
    """
    entries = []
    for path in (PREV_PATH, LOG_PATH):
        try:
            f = open(path, "r")
        except Exception:
            continue
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
                entries.append({"role": pc[0], "content": pc[1],
                                "source": path, "pos": len(entries)})
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass
    return entries


def search(query, limit=SEARCH_DEFAULT_LIMIT):
    """Keyword scan over current + rotated logs.

    Case-insensitive AND-of-words: every query word must occur in the entry;
    ranked by total hit count, recency (later = better) breaking ties. Each
    hit carries its ±1 adjacent entries (prev/next single log lines — the
    codebase counts lines as turns, same as injectRecentLog's last-8). Total
    JSON output is capped at ~2KB (lowest-ranked hits dropped first).

    NOTE: agent_tools.injectRecentLog is intentionally unchanged — it still
    injects the last-8 of the CURRENT log only. This search is the
    cross-rotation recall path (finds pre-/new facts after rotation).
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
    entries = _load_all()
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


def rotate():
    """`/new`: single-generation rotation, flash-cheap.

    Deletes chatlog.prev.jsonl if present, then renames chatlog.jsonl to
    chatlog.prev.jsonl. Memories (memory.txt/user.txt), skills, and pending
    queues (pending_mem.json/pending_skills/) are untouched — clearing the
    chat never clears saved facts. An absent current log is success with
    rotated=False (already a fresh session).
    """
    import os
    rotated = False
    try:
        try:
            os.remove(PREV_PATH)
        except Exception:
            pass
        try:
            os.rename(LOG_PATH, PREV_PATH)
            rotated = True
        except Exception:
            rotated = False
    except Exception:
        rotated = False
    out = {"success": True, "rotated": rotated}
    if rotated:
        out["message"] = ("Started a new session; previous log kept as %s." % PREV_PATH)
    else:
        out["message"] = "Log was already empty; nothing to rotate."
    return out


def _stat_size(path):
    try:
        import os
        return int(os.stat(path)[6])
    except Exception:
        return 0


def _stat_mtime(path):
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


def journey():
    """Time-ordered feed of learning/lifecycle events, mtime ascending.

    Sources: memory.txt/user.txt (mtime+size+usage%), each skills/*.md
    (mtime+size), pending counts (pending_mem.json count, pending_skills/
    count), log state (current + .prev sizes). Missing files are skipped
    (pending counts still report 0 with mtime 0); nothing here ever raises.
    """
    events = []
    # --- curated memories ---
    for target, path in MEM_FILES:
        m = _stat_mtime(path)
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
                       "mtime": m, "size": _stat_size(path),
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
            m = _stat_mtime(fp)
            if m is None:
                continue
            base = fn[:-3]
            events.append({"kind": "skill", "name": base, "path": fp,
                           "mtime": m, "size": _stat_size(fp)})
    except Exception:
        pass
    # --- pending queues (always reported, even when empty) ---
    try:
        import memory as _mem2
        pcount = len(_mem2.list_pending())
    except Exception:
        pcount = 0
    pm = _stat_mtime(PENDING_MEM_PATH)
    events.append({"kind": "pending", "name": PENDING_MEM_PATH,
                   "count": pcount, "mtime": pm if pm is not None else 0,
                   "size": _stat_size(PENDING_MEM_PATH)})
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
            m = _stat_mtime(PENDING_SKILLS_DIR + "/" + fn)
            if m is not None and m > smax:
                smax = m
        if not pfiles:
            try:
                dm = _stat_mtime(PENDING_SKILLS_DIR)
                if dm is not None:
                    smax = dm
            except Exception:
                pass
    except Exception:
        pass
    events.append({"kind": "pending", "name": PENDING_SKILLS_DIR,
                   "count": scount, "mtime": smax})
    # --- logs ---
    for path in (LOG_PATH, PREV_PATH):
        m = _stat_mtime(path)
        if m is None:
            continue
        events.append({"kind": "log", "name": path,
                       "mtime": m, "size": _stat_size(path)})
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


def trajectory(max_pairs=TRAJ_MAX_PAIRS):
    """ShareGPT export across .prev (older) + current (newer) logs.

    {"conversations": [{"from": "human"|"gpt", "value": ...}]} — one human/gpt
    pair per adjacent user→assistant turn pair. Unpaired turns (user with no
    following assistant, stray assistant) are skipped. Capped at 50 pairs
    (most recent win, still time-ordered); values truncated to the 1500-char
    log cap, same as agent_tools.appendChatLog.
    """
    try:
        mp = int(max_pairs)
    except Exception:
        mp = TRAJ_MAX_PAIRS
    if mp < 1:
        mp = 1
    if mp > TRAJ_MAX_PAIRS:
        mp = TRAJ_MAX_PAIRS
    entries = _load_all()
    pairs = []
    i = 0
    n = len(entries)
    while i < n:
        try:
            e = entries[i]
        except Exception:
            i += 1
            continue
        if e.get("role") == "user":
            if i + 1 < n and entries[i + 1].get("role") == "assistant":
                try:
                    u = str(entries[i].get("content", ""))[:TRAJ_VALUE_CAP]
                    a = str(entries[i + 1].get("content", ""))[:TRAJ_VALUE_CAP]
                except Exception:
                    i += 1
                    continue
                pairs.append((u, a))
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
