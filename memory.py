# memory.py — two-store bounded curated memory (Mini Hermes Phase 2).
# MicroPython-safe: utf-8 only, plain substring ops (no `re`), single file
# rewrites like the rest of the codebase. This module OWNS the store files;
# agent_tools.readMemoryFacts/appendMemoryFact are thin compat shims over it.
#
# Stores (Hermes parity, `- ` lines instead of `\u00a7` delimiters):
#   device  memory.txt  cap 2200 chars  (Hermes MEMORY.md)
#   user    user.txt    cap 1375 chars  (Hermes USER.md)
# Target aliases: "memory" == "device" (Hermes name), "user" == "user".
#
# Rules: exact-duplicate add -> success "no duplicate added"; patch/remove use
# unique-substring match (no match -> error with closest entries; ambiguous ->
# error); patch replaces ONLY the matched span, which must occur once in the
# entry; overflow -> ERROR naming the exact chars to free (never silent trim);
# apply_batch(target, ops) checks the limit only on the final result, so one
# call can free space AND add. Every write is injection-scanned first.
#
# security.memory_write_approval in config.yaml (default false): foreground
# writes are STAGED to pending_mem.json instead of applied; approve()/reject()
# consume staged records. Staged patch/remove pin the FULL entry they were
# reviewed against; approve refuses drifted entries.
try:
    import ujson as json
except ImportError:
    import json

MEM_PATH = "memory.txt"
USER_PATH = "user.txt"
PENDING_PATH = "pending_mem.json"
MEM_CAP = 2200
USER_CAP = 1375
_PREVIEW_LEN = 80


def _cap_for(target):
    if target == "device":
        return MEM_CAP
    if target == "user":
        return USER_CAP
    return None


def _path_for(target):
    if target == "device":
        return MEM_PATH
    if target == "user":
        return USER_PATH
    return None


def norm_target(t):
    """Canonical 'device'/'user' or None. Accepts the Hermes 'memory' alias."""
    s = str(t or "").strip().lower()
    if s in ("device", "memory", "mem"):
        return "device"
    if s in ("user", "users"):
        return "user"
    return None


def approval_enabled():
    """True when config.yaml enables the memory write-approval gate."""
    try:
        import config as _cfg
        return bool(_cfg.get_approval("memory", False))
    except Exception:
        return False


# ---------- entries ----------

def _read_raw(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""
    except Exception:
        return ""


def _parse_entries(raw):
    """Lines -> entry list. '- ' prefixed lines are entries; any other
    non-empty line is a legacy entry (old writers always used '- ' too)."""
    out = []
    try:
        lines = str(raw).split("\n")
    except Exception:
        return out
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("- "):
            s = s[2:].strip()
            if not s:
                continue
        out.append(s)
    return out


def _render(entries):
    if not entries:
        return ""
    return "".join("- " + e + "\n" for e in entries)


def _write_entries(target, entries):
    path = _path_for(target)
    with open(path, "w") as f:
        f.write(_render(entries))


def _load(target):
    """Entries for target, migrating legacy/over-cap files oldest-first.

    Existing content is preserved; when it exceeds the cap the oldest entries
    are dropped until it fits, and the trimmed file is written back (one-time).
    """
    entries = _parse_entries(_read_raw(_path_for(target)))
    cap = _cap_for(target)
    if cap is not None and len(_render(entries)) > cap:
        while entries and len(_render(entries)) > cap:
            entries.pop(0)
        try:
            _write_entries(target, entries)
        except OSError:
            pass
    return entries


def read_text(target):
    """Raw rendered store text (compat shape for old readMemoryFacts)."""
    t = norm_target(target)
    if t is None:
        return ""
    return _render(_load(t))


def usage(target):
    """(pct, n_chars, cap) for a store. pct is capped at 100."""
    t = norm_target(target)
    if t is None:
        return (0, 0, 0)
    cap = _cap_for(t)
    n = len(_render(_load(t)))
    pct = int(n * 100 / cap) if cap else 0
    if pct > 100:
        pct = 100
    return (pct, n, cap)


def _header(target, entries):
    cap = _cap_for(target)
    n = len(_render(entries))
    pct = int(n * 100 / cap) if cap else 0
    if pct > 100:
        pct = 100
    title = "USER MEMORY" if target == "user" else "DEVICE MEMORY"
    return "%s [%d%% %d/%d chars]" % (title, pct, n, cap)


def _block(target, entries):
    head = _header(target, entries)
    if not entries:
        return head + "\n(empty)"
    return head + "\n" + _render(entries).rstrip("\n")


def snapshot(target):
    """Frozen text block: header '% used + n/m chars' + entries."""
    t = norm_target(target)
    if t is None:
        return ""
    return _block(t, _load(t))


def snapshot_for_prompt(budget=1200):
    """Both store blocks in one string within budget. Headers always shown;
    entries are dropped oldest-first per store when over budget."""
    try:
        budget = int(budget)
    except Exception:
        budget = 1200
    dent = _load("device")
    uent = _load("user")
    while True:
        body = _block("device", dent) + "\n" + _block("user", uent)
        if len(body) <= budget:
            return body
        # drop the oldest entry from the store holding more entry chars
        dn = len(_render(dent))
        un = len(_render(uent))
        if dn <= 0 and un <= 0:
            return body  # headers alone exceed budget; still show them
        if dn >= un and dent:
            dent.pop(0)
        elif uent:
            uent.pop(0)
        elif dent:
            dent.pop(0)
        else:
            return body


# ---------- injection scan ----------

_INVIS_CODES = (0xAD,
                0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
                0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF)
try:
    _INVIS_CHARS = tuple(chr(c) for c in _INVIS_CODES)
except Exception:
    _INVIS_CHARS = ()

# Small explicit blocklist (lowercase substring match): dangerous device
# imports, socket/exfil tooling, SSH persistence. Kept tiny on purpose —
# bossy English ("you must ...") is common in legitimate notes.
_BLOCKED = ("import machine", "import network", "import os",
            "from machine", "from network", "from os",
            "socket", "authorized_keys", "__import__", "os.system",
            "machine.pin", "network.wlan", "curl ", "wget ")
_EXFIL_VERBS = ("post ", "post(", "posts ", "send ", "sends ", "upload",
                "transmit", "urequests", "requests.")

_HEX = "0123456789ABCDEF"


def _hex4(n):
    n = int(n) & 0xFFFF
    return (_HEX[(n >> 12) & 15] + _HEX[(n >> 8) & 15] +
            _HEX[(n >> 4) & 15] + _HEX[n & 15])


def scan(text):
    """Error string when text must not be stored, else None. Nothing is
    written when this returns non-None."""
    try:
        s = str(text)
    except Exception:
        return "blocked: unreadable content"
    for ch in _INVIS_CHARS:
        try:
            if ch and ch in s:
                return ("blocked: invisible Unicode U+%s — remove it and retry" % _hex4(ord(ch)))
        except Exception:
            pass
    try:
        low = s.lower()
    except Exception:
        low = ""
    for b in _BLOCKED:
        if b in low:
            return ("blocked: disallowed pattern '%s' — memory enters the system "
                    "prompt, so code/exfil text is never stored" % b.strip())
    if "http://" in low or "https://" in low:
        for v in _EXFIL_VERBS:
            if v in low:
                return ("blocked: URL + exfil pattern ('%s' with a link) — memory "
                        "enters the system prompt, so exfil text is never stored" % v.strip())
    return None


# ---------- matching ----------

def _words(s):
    """Lowercase alphanumeric tokens without `re`."""
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


def _preview(e):
    e = str(e)
    if len(e) > _PREVIEW_LEN:
        return e[:_PREVIEW_LEN] + "..."
    return e


def _find_unique(entries, old):
    """(index, ambiguous). old must occur in exactly one entry."""
    hits = []
    for i, e in enumerate(entries):
        if old in e:
            hits.append(i)
    if not hits:
        return None, False
    if len(hits) > 1:
        return None, True
    return hits[0], False


def _closest(entries, old, k=3):
    """Up to k closest entries by shared-word overlap, truncated."""
    w = _words(old)
    if not w:
        return [_preview(e) for e in entries[:k]]
    wset = {}
    for x in w:
        wset[x] = True
    scored = []
    for i, e in enumerate(entries):
        ew = _words(e)
        eset = {}
        for x in ew:
            eset[x] = True
        hit = 0
        for x in wset:
            if x in eset:
                hit += 1
        score = hit * 1000 // len(w) if w else 0
        scored.append((score, i))
    # insertion sort, best first (tiny lists; no key-sort dependency)
    for a in range(len(scored)):
        for b in range(a + 1, len(scored)):
            if scored[b][0] > scored[a][0] or (scored[b][0] == scored[a][0] and scored[b][1] < scored[a][1]):
                scored[a], scored[b] = scored[b], scored[a]
    return [_preview(entries[i]) for _, i in scored[:k] if i < len(entries)]


def _usage_pct(target, n):
    cap = _cap_for(target)
    pct = int(n * 100 / cap) if cap else 0
    if pct > 100:
        pct = 100
    return "%d%% %d/%d chars" % (pct, n, cap)


def _no_match(target, old, verb, entries):
    err = ("No entry matched '%s'. Retry the %s with old_text copied verbatim "
           "from one entry below (unique substring)." % (old, verb))
    out = {"success": False, "error": err, "usage": _usage_pct(target, len(_render(entries)))}
    if entries:
        out["closest_entries"] = _closest(entries, old)
    return out


def _ambiguous(old, entries):
    hits = [i for i, e in enumerate(entries) if old in e]
    return {"success": False,
            "error": ("Multiple entries matched '%s'. Be more specific: old_text "
                      "must occur in exactly one entry." % old),
            "matches": [_preview(entries[i]) for i in hits[:5]]}


def _overflow_add(target, entries, content):
    cap = _cap_for(target)
    new_total = len(_render(entries + [content]))
    need = new_total - cap
    return {"success": False,
            "error": ("Memory at %s; adding this entry (%d chars) would exceed the limit "
                      "by %d chars. Free at least %d chars: retry as ONE batch that removes "
                      "or shortens stale entries AND adds the new one — the limit is checked "
                      "only on the batch result." % (_usage_pct(target, len(_render(entries))),
                                                     len(content), need, need)),
            "need_free": need,
            "usage": _usage_pct(target, len(_render(entries))),
            "current_entries": list(entries)}


def _clean_line(s):
    s = str(s or "").replace("\r", " ").replace("\n", " ")
    # collapse whitespace runs without `re`
    parts = s.split()
    return " ".join(parts)


# ---------- pending (write_approval staging) ----------

def _read_pending():
    try:
        with open(PENDING_PATH, "r") as f:
            d = json.loads(f.read() or "[]")
    except Exception:
        return []
    if not isinstance(d, list):
        return []
    return [r for r in d if isinstance(r, dict)]


def _write_pending(recs):
    with open(PENDING_PATH, "w") as f:
        f.write(json.dumps(recs))


def _next_id(recs):
    top = 0
    for r in recs:
        try:
            i = int(r.get("id", 0))
            if i > top:
                top = i
        except Exception:
            pass
    return top + 1


def _stage(rec):
    recs = _read_pending()
    rec["id"] = _next_id(recs)
    recs.append(rec)
    _write_pending(recs)
    return {"success": True, "staged": True, "pending_id": rec["id"],
            "message": ("Write approval is on: staged as #%d. Review with /api/memory "
                        "pending, then approve or reject." % rec["id"])}


def list_pending():
    """Staged write records (oldest first). Never raises."""
    try:
        return _read_pending()
    except Exception:
        return []


def _sel_ids(recs, sel):
    if sel == "all" or sel is None:
        return [r.get("id") for r in recs]
    ids = sel if isinstance(sel, list) else [sel]
    out = []
    for x in ids:
        if isinstance(x, str) and x.strip().lower() == "all":
            return [r.get("id") for r in recs]
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


def _stale_msg(entry):
    return ("Entry changed since it was staged, so this write was not applied: '%s' is "
            "no longer in memory as reviewed. Recreate the change against the current "
            "entry or reject it; the pending record has been preserved." % _preview(entry))


def _apply_record(rec):
    """Replay one staged record. Returns (ok, info_dict). Never consumes on fail."""
    t = norm_target(rec.get("target", "device"))
    if t is None:
        return False, {"error": "bad staged target"}
    act = str(rec.get("action", "") or "").strip().lower()
    entries = _load(t)
    cap = _cap_for(t)
    if act == "add":
        content = _clean_line(rec.get("content", ""))
        if not content:
            return False, {"error": "staged add has no content"}
        err = scan(content)
        if err:
            return False, {"error": err}
        if content in entries:
            return True, {"message": "Entry already exists (no duplicate added)."}
        if len(_render(entries + [content])) > cap:
            need = len(_render(entries + [content])) - cap
            return False, {"error": "still over limit: free at least %d chars first" % need,
                           "need_free": need}
        entries = entries + [content]
        _write_entries(t, entries)
        return True, {"message": "Entry added."}
    if act in ("patch", "remove"):
        pin = rec.get("matched_entry", "")
        if not pin:
            return False, {"error": ("This destructive pending write predates entry pinning and "
                                     "cannot be verified; nothing was applied. Reject it and recreate "
                                     "the change.")}
        idx = None
        for i, e in enumerate(entries):
            if e == pin:
                idx = i
                break
        if idx is None:
            return False, {"error": _stale_msg(pin)}
        if act == "remove":
            entries = entries[:idx] + entries[idx + 1:]
            _write_entries(t, entries)
            return True, {"message": "Entry removed."}
        new_text = _clean_line(rec.get("content", ""))
        old = str(rec.get("old_text", "") or "")
        if not new_text:
            return False, {"error": "staged patch has no content"}
        err = scan(new_text)
        if err:
            return False, {"error": err}
        if entries[idx].count(old) > 1:
            return False, {"error": ("'%s' appears %d times in the matched entry; include more "
                                     "surrounding text so it occurs once." % (old, entries[idx].count(old)))}
        if old not in entries[idx]:
            return False, {"error": _stale_msg(pin)}
        after = entries[idx].replace(old, new_text, 1)
        if after == entries[idx]:
            return False, {"error": "Patch is a no-op."}
        err = scan(after)
        if err:
            return False, {"error": err}
        trial = entries[:idx] + [after] + entries[idx + 1:]
        if len(_render(trial)) > cap:
            need = len(_render(trial)) - cap
            return False, {"error": "patch over limit: free at least %d chars first" % need,
                           "need_free": need}
        _write_entries(t, trial)
        return True, {"message": "Entry patched."}
    if act == "batch":
        ops = rec.get("operations") or []
        if not isinstance(ops, list) or not ops:
            return False, {"error": "staged batch is empty"}
        return _run_batch(t, ops, staged=True)
    return False, {"error": "Unknown staged action '%s'." % act}


def approve(sel="all"):
    """Apply staged records by id (or 'all'). Drifted/over-limit records are
    refused and KEPT; successes are consumed. Single pending rewrite."""
    recs = _read_pending()
    want = _sel_ids(recs, sel)
    approved = []
    failed = {}
    keep = []
    for r in recs:
        try:
            rid = int(r.get("id", -1))
        except Exception:
            keep.append(r)
            continue
        if rid not in want:
            keep.append(r)
            continue
        try:
            ok, info = _apply_record(r)
        except Exception as e:
            ok, info = False, {"error": "apply failed: %s" % str(e)[:100]}
        if ok:
            approved.append(rid)
        else:
            failed[str(rid)] = info.get("error", "apply failed")
            keep.append(r)
    _write_pending(keep)
    out = {"success": len(failed) == 0, "approved": approved, "failed": failed,
           "pending": list(keep)}
    if approved and not failed:
        out["message"] = "Approved %d write(s)." % len(approved)
    elif not approved and not failed:
        out["message"] = "Nothing pending."
    return out


def reject(sel="all"):
    """Drop staged records by id (or 'all'). Single pending rewrite."""
    recs = _read_pending()
    want = _sel_ids(recs, sel)
    dropped = []
    keep = []
    for r in recs:
        try:
            rid = int(r.get("id", -1))
        except Exception:
            keep.append(r)
            continue
        if rid in want:
            dropped.append(rid)
        else:
            keep.append(r)
    _write_pending(keep)
    missing = [x for x in want if x not in dropped]
    out = {"success": True, "rejected": dropped, "pending": list(keep)}
    if missing:
        out["not_found"] = missing
    return out


# ---------- mutations ----------

def add(target, text):
    t = norm_target(target)
    if t is None:
        return {"success": False, "error": "Invalid target '%s'. Use 'device' or 'user'." % str(target)[:40]}
    content = _clean_line(text)
    if not content:
        return {"success": False, "error": "Content is required for 'add'."}
    err = scan(content)
    if err:
        return {"success": False, "error": err}
    entries = _load(t)
    if content in entries:
        return {"success": True, "duplicate": True,
                "message": "Entry already exists (no duplicate added).",
                "usage": _usage_pct(t, len(_render(entries))),
                "entry_count": len(entries)}
    if len(_render(entries + [content])) > _cap_for(t):
        return _overflow_add(t, entries, content)
    if approval_enabled():
        return _stage({"target": t, "action": "add", "content": content,
                       "old_text": "", "matched_entry": ""})
    try:
        _write_entries(t, entries + [content])
    except OSError as e:
        return {"success": False, "error": "write failed: %s" % str(e)[:80]}
    return {"success": True, "message": "Entry added.",
            "usage": _usage_pct(t, len(_render(entries + [content]))),
            "entry_count": len(entries) + 1}


def patch(target, old_text, content):
    t = norm_target(target)
    if t is None:
        return {"success": False, "error": "Invalid target '%s'. Use 'device' or 'user'." % str(target)[:40]}
    old = _clean_line(old_text)
    if not old:
        return {"success": False,
                "error": ("'patch' needs old_text — a short unique substring of the entry to patch. "
                          "Reissue with old_text set to part of one current entry.")}
    new_text = _clean_line(content)
    if not new_text:
        return {"success": False, "error": "content (new text for the old_text span) is required for 'patch'."}
    err = scan(new_text)
    if err:
        return {"success": False, "error": err}
    entries = _load(t)
    idx, amb = _find_unique(entries, old)
    if amb:
        return _ambiguous(old, entries)
    if idx is None:
        return _no_match(t, old, "patch", entries)
    if entries[idx].count(old) > 1:
        return {"success": False,
                "error": ("'%s' appears %d times in the matched entry, and patch edits one span. "
                          "Include more surrounding text so old_text occurs once." % (old, entries[idx].count(old)))}
    after = entries[idx].replace(old, new_text, 1)
    if after == entries[idx]:
        return {"success": False, "error": "Patch is a no-op: it leaves the entry unchanged."}
    err = scan(after)
    if err:
        return {"success": False, "error": err}
    trial = entries[:idx] + [after] + entries[idx + 1:]
    if len(_render(trial)) > _cap_for(t):
        need = len(_render(trial)) - _cap_for(t)
        return {"success": False,
                "error": ("Patch would put memory at %s (over by %d chars). Shorten the new text, or "
                          "remove other stale entries to make room, then retry." % (
                              _usage_pct(t, len(_render(trial))), need)),
                "need_free": need, "usage": _usage_pct(t, len(_render(entries))),
                "current_entries": list(entries)}
    if approval_enabled():
        return _stage({"target": t, "action": "patch", "content": new_text,
                       "old_text": old, "matched_entry": entries[idx]})
    try:
        _write_entries(t, trial)
    except OSError as e:
        return {"success": False, "error": "write failed: %s" % str(e)[:80]}
    return {"success": True, "message": "Entry patched.",
            "usage": _usage_pct(t, len(_render(trial))),
            "entry_count": len(trial)}


def remove(target, old_text):
    t = norm_target(target)
    if t is None:
        return {"success": False, "error": "Invalid target '%s'. Use 'device' or 'user'." % str(target)[:40]}
    old = _clean_line(old_text)
    if not old:
        return {"success": False,
                "error": ("'remove' needs old_text — a short unique substring of the entry to remove. "
                          "Reissue with old_text set to part of one current entry.")}
    entries = _load(t)
    idx, amb = _find_unique(entries, old)
    if amb:
        return _ambiguous(old, entries)
    if idx is None:
        return _no_match(t, old, "remove", entries)
    if approval_enabled():
        return _stage({"target": t, "action": "remove", "content": "",
                       "old_text": old, "matched_entry": entries[idx]})
    gone = entries[idx]
    try:
        _write_entries(t, entries[:idx] + entries[idx + 1:])
    except OSError as e:
        return {"success": False, "error": "write failed: %s" % str(e)[:80]}
    left = entries[:idx] + entries[idx + 1:]
    return {"success": True, "message": "Entry removed.", "removed_entry": _preview(gone),
            "usage": _usage_pct(t, len(_render(left))),
            "entry_count": len(left)}


def _op_text(op):
    for k in ("content", "text", "new_text"):
        v = op.get(k)
        if v is not None and str(v) != "":
            return str(v)
    return ""


def _run_batch(t, ops, staged=False):
    """Shared batch engine. staged=True pins come from the record (approve
    path) instead of fresh matching. Returns (ok, info) for approve, or the
    result dict for the direct path."""
    cap = _cap_for(t)
    entries = _load(t)
    # validate + scan everything before touching state
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            return (False, {"error": "Operation %d: not an object." % (i + 1)}) if staged else \
                {"success": False, "error": "Operation %d: not an object." % (i + 1)}
        act = str(op.get("action", "") or "").strip().lower()
        content = _clean_line(_op_text(op))
        old = _clean_line(op.get("old_text", ""))
        pos = "Operation %d (%s)" % (i + 1, act or "unknown")
        if act == "add" and not content:
            msg = "%s: content is required." % pos
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        if act == "patch" and (not old or not content):
            msg = "%s: old_text and content are both required." % pos
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        if act == "remove" and not old:
            msg = "%s: old_text is required." % pos
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        if act not in ("add", "patch", "remove"):
            msg = "%s: unknown action. Use add, patch, or remove." % pos
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        if act in ("add", "patch"):
            err = scan(content)
            if err:
                msg = "%s: %s" % (pos, err)
                return (False, {"error": msg}) if staged else {"success": False, "error": msg}
    working = list(entries)
    for i, op in enumerate(ops):
        act = str(op.get("action", "") or "").strip().lower()
        content = _clean_line(_op_text(op))
        old = _clean_line(op.get("old_text", ""))
        pos = "Operation %d (%s)" % (i + 1, act or "unknown")
        if act == "add":
            if content not in working:  # idempotent: skip duplicates
                working.append(content)
            continue
        pin = op.get("matched_entry", "") if staged else ""
        if staged and not pin:
            msg = ("%s: this destructive pending write predates entry pinning and cannot be "
                   "verified; nothing was applied. Reject it and recreate the change." % pos)
            return False, {"error": msg}
        if staged:
            idx = None
            for j, e in enumerate(working):
                if e == pin:
                    idx = j
                    break
            if idx is None:
                return False, {"error": "%s: %s" % (pos, _stale_msg(pin))}
        else:
            idx, amb = _find_unique(working, old)
            if amb:
                msg = "%s: '%s' matched multiple entries — be more specific. No operations were applied." % (pos, old)
                return (False, {"error": msg}) if staged else \
                    {"success": False, "error": msg, "usage": _usage_pct(t, len(_render(entries)))}
            if idx is None:
                miss = _no_match(t, old, act, working)
                msg = "%s: %s No operations were applied." % (pos, miss["error"])
                out = {"success": False, "error": msg, "usage": miss["usage"]}
                if "closest_entries" in miss:
                    out["closest_entries"] = miss["closest_entries"]
                return (False, {"error": msg}) if staged else out
        if act == "remove":
            working = working[:idx] + working[idx + 1:]
            continue
        # patch
        if working[idx].count(old) > 1:
            msg = ("%s: '%s' appears %d times in the matched entry. Include more surrounding "
                   "text so it occurs once. No operations were applied." % (pos, old, working[idx].count(old)))
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        if old not in working[idx]:
            msg = "%s: %s No operations were applied." % (pos, _stale_msg(working[idx]))
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        after = working[idx].replace(old, content, 1)
        if after == working[idx]:
            msg = "%s: patch is a no-op. No operations were applied." % pos
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        err = scan(after)
        if err:
            msg = "%s: %s No operations were applied." % (pos, err)
            return (False, {"error": msg}) if staged else {"success": False, "error": msg}
        working = working[:idx] + [after] + working[idx + 1:]
    new_total = len(_render(working))
    if new_total > cap:
        need = new_total - cap
        msg = ("Applying all %d operations would put memory at %s (over by %d chars). Add removes "
               "or shortening patches of other stale entries to the same batch, then retry. "
               "No operations were applied." % (len(ops), _usage_pct(t, new_total), need))
        out = {"success": False, "error": msg, "need_free": need, "usage": _usage_pct(t, len(_render(entries)))}
        if len(ops) == 1 and ops[0].get("action") == "add":
            return (False, out) if staged else _overflow_add(t, entries, _clean_line(_op_text(ops[0])))
        return (False, {"error": msg, "need_free": need}) if staged else out
    try:
        _write_entries(t, working)
    except OSError as e:
        msg = "write failed: %s" % str(e)[:80]
        return (False, {"error": msg}) if staged else {"success": False, "error": msg}
    done = {"success": True, "message": "Applied %d operation(s)." % len(ops),
            "usage": _usage_pct(t, new_total), "entry_count": len(working)}
    return (True, done) if staged else done


def apply_batch(target, ops):
    """Atomically apply ops against one store; the cap is checked only on the
    final result. Any failure writes NOTHING. With write_approval on, the
    batch is staged (pins resolved now) instead of applied."""
    t = norm_target(target)
    if t is None:
        return {"success": False, "error": "Invalid target '%s'. Use 'device' or 'user'." % str(target)[:40]}
    if not isinstance(ops, list) or not ops:
        return {"success": False, "error": "operations must be a non-empty list."}
    if approval_enabled():
        entries = _load(t)
        pinned = []
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                return {"success": False, "error": "Operation %d: not an object." % (i + 1)}
            c = dict(op)
            act = str(c.get("action", "") or "").strip().lower()
            if act in ("patch", "remove"):
                old = _clean_line(c.get("old_text", ""))
                idx, amb = _find_unique(entries, old)
                pos = "Operation %d (%s)" % (i + 1, act)
                if amb:
                    return _ambiguous(old, entries)
                if idx is None:
                    miss = _no_match(t, old, act, entries)
                    return {"success": False,
                            "error": "%s: %s" % (pos, miss["error"]),
                            "closest_entries": miss.get("closest_entries", [])}
                c["matched_entry"] = entries[idx]
                # resolve sequentially so later ops see earlier ones
                if act == "remove":
                    entries = entries[:idx] + entries[idx + 1:]
                else:
                    content = _clean_line(_op_text(c))
                    entries = entries[:idx] + [entries[idx].replace(old, content, 1)] + entries[idx + 1:]
            elif act == "add":
                content = _clean_line(_op_text(c))
                if content and content not in entries:
                    entries.append(content)
            pinned.append(c)
        return _stage({"target": t, "action": "batch", "content": "",
                       "old_text": "", "matched_entry": "", "operations": pinned})
    return _run_batch(t, ops)
