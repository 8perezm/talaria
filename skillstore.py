# skillstore.py — single-file user skills (Mini Hermes Phase 3).
# MicroPython-safe: utf-8 only, plain substring ops (no `re`), bounded reads,
# lazy `os` imports. This module OWNS the skills store; the tools
# (skills / skill_view) and server.py /api/skills are thin shims over it.
#
# Store: `skills/<name>.md`, name = lowercase alnum+hyphen, <=40 chars.
# Each skill <=3KB, max 12 skills. First line `// desc: <<=120 chars>`,
# then Markdown body with sections
# `# Title / When to use / Procedure / Pitfalls / Verification`
# (presence validated on create/patch — missing sections WARN, never block).
#
# Prompt carries the L0 index only (names+descs, <=1KB); full text loads on
# demand via skill_view. Staged /learn drafts live under `pending_skills/`
# and are NEVER loadable until approved.
#
# security.skills_write_approval in config.yaml (DEFAULT TRUE — deliberately
# safer than memory's default-false, because a skill enters the system prompt
# and a bad skill poisons every turn until a human notices). Foreground
# create/patch/delete are STAGED while the flag is on; propose() (the /learn
# path) ALWAYS stages. Approve refuses drifted records (content-hash pin) and
# keeps them for review.
#
# Bundles: bundles.json {name: [skill names]}; expand_bundle() concatenates
# bodies, skipping missing skills (noted, never fatal).
try:
    import ujson as json
except ImportError:
    import json

SKILLS_DIR = "opt/data/skills"
PENDING_DIR = "opt/data/pending_skills"
BUNDLES_PATH = "opt/data/bundles.json"
SKILL_MAX_BYTES = 3072  # 3KB per skill
SKILL_MAX_COUNT = 12
NAME_MAX = 40
DESC_MAX = 120
INDEX_BUDGET = 1024  # L0 index + instruction line, prompt section

_DESC_PREFIX = "// desc:"

_LEARN_LINE = ("Skills below are all usable - load the full skill with skill_view "
               "{\"name\": ...} (bundles as \"bundle:<name>\") when relevant; "
               "/learn drafts are staged for approval, never auto-applied.")


def approval_enabled():
    """True unless config.yaml sets security.skills_write_approval false."""
    try:
        import config as _cfg
        return bool(_cfg.get_approval("skills", True))
    except Exception:
        return True


# ---------- names / format ----------

def _name_error(name):
    """Error text for a bad skill name, else ''."""
    try:
        s = str(name or "").strip()
    except Exception:
        return "name is required"
    if not s:
        return "name is required (lowercase alnum+hyphen, <=40 chars)"
    if len(s) > NAME_MAX:
        return "name too long (%d chars, max %d)" % (len(s), NAME_MAX)
    for ch in s:
        ok = ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "-"
        if not ok:
            return ("bad name '%s': use lowercase letters, digits and hyphen only "
                    "(<=40 chars)" % s[:40])
    first, last = s[0], s[-1]
    if not ((("a" <= first <= "z") or ("0" <= first <= "9")) and
            (("a" <= last <= "z") or ("0" <= last <= "9"))):
        return "name must start and end with a letter or digit"
    return ""


def _norm_content(content):
    try:
        s = str(content or "")
    except Exception:
        return ""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _size_error(content):
    try:
        n = len(content.encode("utf-8"))
    except Exception:
        n = len(content)
    if n > SKILL_MAX_BYTES:
        return ("skill too large (%dB, max %dB)" % (n, SKILL_MAX_BYTES))
    return ""


def parse_desc(content):
    """(desc, err). First line must be '// desc: <text 1..120 chars>'."""
    try:
        first = str(content).split("\n", 1)[0].strip()
    except Exception:
        return "", "unreadable content"
    if not first.startswith(_DESC_PREFIX):
        return "", "first line must be '// desc: <summary, <=120 chars>'"
    desc = first[len(_DESC_PREFIX):].strip()
    if not desc:
        return "", "'// desc:' summary must not be empty"
    if len(desc) > DESC_MAX:
        return "", "'// desc:' summary too long (%d chars, max %d)" % (len(desc), DESC_MAX)
    return desc, ""


def section_warnings(content):
    """Warn-not-block list for missing doc sections ([] when complete)."""
    try:
        parts = str(content).split("\n", 1)
        body = parts[1] if len(parts) > 1 else ""
    except Exception:
        return ["missing section: body"]
    miss = []
    has_title = False
    try:
        for ln in body.split("\n"):
            if ln.strip().startswith("#"):
                has_title = True
                break
    except Exception:
        pass
    if not has_title:
        miss.append("Title")
    try:
        low = body.lower()
    except Exception:
        low = ""
    if "when to use" not in low:
        miss.append("When to use")
    if "procedure" not in low:
        miss.append("Procedure")
    if "pitfall" not in low:
        miss.append("Pitfalls")
    if "verificat" not in low:
        miss.append("Verification")
    return ["missing section: " + m for m in miss]


# ---------- quarantine scan ----------

_INVIS_CODES = (0xAD,
                0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
                0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF)
try:
    _INVIS_CHARS = tuple(chr(c) for c in _INVIS_CODES)
except Exception:
    _INVIS_CHARS = ()

_HEX = "0123456789ABCDEF"


def _hex4(n):
    n = int(n) & 0xFFFF
    return (_HEX[(n >> 12) & 15] + _HEX[(n >> 8) & 15] +
            _HEX[(n >> 4) & 15] + _HEX[n & 15])


def _hash8(s):
    """FNV-1a 32-bit hex (8 chars). Plain ops only — the drift pin."""
    h = 2166136261
    try:
        for ch in str(s):
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    except Exception:
        pass
    out = ""
    for shift in (28, 24, 20, 16, 12, 8, 4, 0):
        out += _HEX[(h >> shift) & 15]
    return out


# Prompt-injection directives: a skill enters the system prompt, so any of
# these is a quarantine refusal, not a warning.
_INJECT = ("ignore previous instructions", "ignore all previous instructions",
           "disregard previous instructions", "disregard your instructions",
           "override your instructions", "bypass your instructions",
           "reveal system prompt", "reveal your system prompt",
           "reveal your instructions", "show system prompt",
           "show me your system prompt", "print system prompt",
           "print your system prompt", "exfiltrate", "exfiltration",
           "jailbreak")
# Same code/exfil spirit as memory.py: skills enter the prompt, so device
# imports and socket/exfil tooling are never stored.
_BLOCKED = ("import machine", "import network", "import os",
            "from machine", "from network", "from os",
            "socket", "authorized_keys", "__import__", "os.system",
            "machine.pin", "network.wlan", "curl ", "wget ")
_EXFIL_VERBS = ("post ", "post(", "posts ", "send ", "sends ", "upload",
                "transmit", "urequests", "requests.")


def scan(text):
    """Error string when text must not be stored, else None."""
    try:
        s = str(text)
    except Exception:
        return "blocked: unreadable content"
    for ch in _INVIS_CHARS:
        try:
            if ch and ch in s:
                return ("blocked: invisible Unicode U+%s - remove it and retry" % _hex4(ord(ch)))
        except Exception:
            pass
    try:
        low = s.lower()
    except Exception:
        low = ""
    for p in _INJECT:
        if p in low:
            return ("blocked: prompt-injection directive '%s' - skills enter the system "
                    "prompt, so instruction-override text is never stored" % p)
    for b in _BLOCKED:
        if b in low:
            return ("blocked: disallowed pattern '%s' - skills enter the system "
                    "prompt, so code/exfil text is never stored" % b.strip())
    if "http://" in low or "https://" in low:
        for v in _EXFIL_VERBS:
            if v in low:
                return ("blocked: URL + exfil pattern ('%s' with a link) - skills "
                        "enter the system prompt, so exfil text is never stored" % v.strip())
    return None


# ---------- store ----------

def _ensure_dir(path):
    try:
        import fsutil as _fs
        try:
            _fs.ensure_data_tree()
        except Exception:
            pass
    except Exception:
        pass
    import os
    for cand in (str(path),):
        cur = ""
        for seg in cand.replace("\\", "/").split("/"):
            if not seg or seg == ".":
                continue
            cur = seg if not cur else cur + "/" + seg
            try:
                os.mkdir(cur)
            except Exception:
                pass
    try:
        import fsutil as _fs2
        try:
            fp = _fs2.full(str(path))
            if fp != str(path):
                cur = ""
                # absolute mkdir chain without os.makedirs (MicroPython-safe)
                stripped = fp.replace("\\", "/")
                prefix = ""
                if stripped.startswith("/"):
                    prefix = "/"
                    stripped = stripped[1:]
                for seg in stripped.split("/"):
                    if not seg:
                        continue
                    cur = (prefix + seg) if not cur or cur == "/" else cur + "/" + seg
                    try:
                        os.mkdir(cur)
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        pass


def _path_for(name):
    return SKILLS_DIR + "/" + name + ".md"


def _read_file(path, limit):
    try:
        with open(path, "r") as f:
            try:
                return f.read(limit)
            except TypeError:
                return f.read()  # very old MicroPython read() takes no size
    except OSError:
        return None
    except Exception:
        return None


def _list_names():
    """Sorted valid skill names (never raises)."""
    import os
    try:
        files = os.listdir(SKILLS_DIR)
    except Exception:
        return []
    out = []
    for fn in files:
        try:
            if isinstance(fn, bytes):
                fn = fn.decode()
        except Exception:
            continue
        if not fn.endswith(".md") or len(fn) <= 3:
            continue
        base = fn[:-3]
        if not _name_error(base):
            out.append(base)
    try:
        out.sort()
    except Exception:
        pass
    return out


def _read_desc(name):
    """Short desc for the index; '' when unreadable (never raises)."""
    t = _read_file(_path_for(name), 256)
    if not t:
        return ""
    try:
        first = t.split("\n", 1)[0].strip()
    except Exception:
        return ""
    if not first.startswith(_DESC_PREFIX):
        return ""
    return first[len(_DESC_PREFIX):].strip()[:DESC_MAX]


def index():
    """L0 list [{name, desc}] sorted by name. Bounded: one ~256B head read
    per skill, 12 skills max."""
    return [{"name": n, "desc": _read_desc(n)} for n in _list_names()]


def _fit_lines(entries, room):
    """Fit 'name: desc' lines into room chars. Descs shrink evenly first
    (names stay visible); entries drop from the end only as a last resort."""
    items = [{"name": e["name"], "desc": e["desc"]} for e in entries]
    while items:
        n = len(items)
        per = room // n if n else room
        ok = True
        out = []
        for it in items:
            allow = per - len(it["name"]) - 3  # ": " + "\n"
            if allow < 8:
                ok = False
                break
            d = it["desc"]
            if len(d) > allow:
                cut = allow - 3
                if cut < 8:
                    ok = False
                    break
                d = d[:cut].rstrip() + "..."
            out.append("%s: %s" % (it["name"], d))
        total = 0
        for s in out:
            total += len(s) + 1
        if ok and total <= room:
            return out
        items = items[:-1]
    return []


def render_index(budget=INDEX_BUDGET):
    """L0 index text within budget chars (entries only, no header)."""
    try:
        budget = int(budget)
    except Exception:
        budget = INDEX_BUDGET
    if budget <= 0:
        return ""
    lines = _fit_lines(index(), budget)
    text = "\n".join(lines)
    return text[:budget]


def prompt_section(budget=INDEX_BUDGET):
    """Full L0 prompt section (instruction line + index) within budget.
    '' when zero skills — the section is omitted entirely then."""
    try:
        budget = int(budget)
    except Exception:
        budget = INDEX_BUDGET
    entries = index()
    if not entries:
        return ""
    line = _LEARN_LINE
    if len(line) + 1 >= budget:
        return line[:budget]
    room = budget - len(line) - 1
    lines = _fit_lines(entries, room)
    return line + "\n" + "\n".join(lines)


def view(name):
    """Full skill file (<=3KB). Staged drafts are NOT here — only approved
    skills under skills/ are loadable."""
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    t = _read_file(_path_for(s), SKILL_MAX_BYTES + 1)
    if t is None:
        return {"success": False,
                "error": "unknown skill '%s'. List names with skills." % s[:40]}
    if len(t) > SKILL_MAX_BYTES:
        t = t[:SKILL_MAX_BYTES]
    desc, _ = parse_desc(t)
    return {"success": True, "name": s, "desc": desc, "content": t,
            "size": len(t), "warnings": section_warnings(t)}


# ---------- pending (write_approval staging) ----------

def _pending_path(pid):
    return PENDING_DIR + "/" + str(pid) + ".json"


def _read_pending():
    import os
    try:
        files = os.listdir(PENDING_DIR)
    except Exception:
        return []
    recs = []
    for fn in files:
        try:
            if isinstance(fn, bytes):
                fn = fn.decode()
        except Exception:
            continue
        if not fn.endswith(".json"):
            continue
        raw = _read_file(PENDING_DIR + "/" + fn, 8192)
        if not raw:
            continue
        try:
            r = json.loads(raw)
        except Exception:
            continue
        if isinstance(r, dict) and r.get("id") is not None:
            recs.append(r)
    # insertion sort by id (tiny lists; no key-sort dependency)
    for a in range(len(recs)):
        for b in range(a + 1, len(recs)):
            try:
                if int(recs[b]["id"]) < int(recs[a]["id"]):
                    recs[a], recs[b] = recs[b], recs[a]
            except Exception:
                pass
    return recs


def _write_pending_file(rec):
    _ensure_dir(PENDING_DIR)
    with open(_pending_path(rec["id"]), "w") as f:
        f.write(json.dumps(rec))


def _remove_pending_file(pid):
    import os
    try:
        os.remove(_pending_path(pid))
    except Exception:
        pass


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


def _gist(kind, name, content, old_text=""):
    n = str(name)[:40]
    if kind == "delete":
        return "delete skill '%s'" % n
    try:
        size = len(str(content).encode("utf-8"))
    except Exception:
        size = len(str(content))
    if kind == "patch":
        o = str(old_text or "")[:40].replace("\n", " ")
        return "patch skill '%s': '%s...' (%dB new)" % (n, o, size)
    if kind == "propose":
        return "propose skill '%s' /learn draft (%dB)" % (n, size)
    return "create skill '%s' (%dB)" % (n, size)


def _stage(kind, name, content, old_text, base):
    recs = _read_pending()
    rec = {"id": _next_id(recs), "kind": kind, "name": name,
           "content": content, "old_text": old_text, "base": base,
           "gist": _gist(kind, name, content, old_text)}
    _write_pending_file(rec)
    return {"success": True, "staged": True, "pending_id": rec["id"],
            "gist": rec["gist"],
            "message": ("Write approval is on: staged as #%d (%s). Review with "
                        "GET /api/skills?pending=1, then approve or reject." % (rec["id"], rec["gist"]))}


def list_pending():
    """Staged skill writes (oldest first). Never raises."""
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


def _stale_msg(name):
    return ("Skill '%s' changed since it was staged, so this write was not applied. "
            "Recreate the change against the current file or reject it; the pending "
            "record has been preserved." % str(name)[:40])


def _write_skill(name, content):
    _ensure_dir(SKILLS_DIR)
    with open(_path_for(name), "w") as f:
        f.write(content)


def _delete_skill(name):
    import os
    os.remove(_path_for(name))


def _current_hash(name):
    t = _read_file(_path_for(name), SKILL_MAX_BYTES + 1)
    if t is None:
        return None
    return _hash8(t)


def _apply_record(rec):
    """Replay one staged record. Returns (ok, info). Never consumes on fail."""
    kind = str(rec.get("kind", "") or "").strip().lower()
    name = str(rec.get("name", "") or "").strip()
    if _name_error(name):
        return False, {"error": "bad staged name"}
    base = str(rec.get("base", "") or "")
    content = rec.get("content", "")
    if content is None:
        content = ""
    content = _norm_content(content)
    if kind in ("create", "propose"):
        if base != "":
            return False, {"error": "unverifiable staged record (no base pin); reject and recreate"}
        if _read_file(_path_for(name), 1) is not None:
            return False, {"error": "skill '%s' already exists; reject or delete it first" % name[:40]}
        if content:
            err = scan(content)
            if err:
                return False, {"error": err}
            err = _size_error(content)
            if err:
                return False, {"error": err}
            _, derr = parse_desc(content)
            if derr:
                return False, {"error": derr}
        elif kind == "create":
            return False, {"error": "staged create has no content"}
        if len(_list_names()) >= SKILL_MAX_COUNT:
            return False, {"error": "skill store full (%d max)" % SKILL_MAX_COUNT}
        if not content:
            return False, {"error": "staged draft is empty"}
        _write_skill(name, content)
        return True, {"message": "Skill '%s' created." % name[:40]}
    if kind == "patch":
        cur = _current_hash(name)
        if cur is None:
            return False, {"error": "skill '%s' is gone; nothing to patch" % name[:40]}
        if cur != base:
            return False, {"error": _stale_msg(name)}
        err = scan(content)
        if err:
            return False, {"error": err}
        err = _size_error(content)
        if err:
            return False, {"error": err}
        _, derr = parse_desc(content)
        if derr:
            return False, {"error": "patched skill " + derr}
        _write_skill(name, content)
        return True, {"message": "Skill '%s' patched." % name[:40]}
    if kind == "delete":
        cur = _current_hash(name)
        if cur is None:
            return True, {"message": "Skill '%s' already removed." % name[:40]}
        if cur != base:
            return False, {"error": _stale_msg(name)}
        _delete_skill(name)
        return True, {"message": "Skill '%s' deleted." % name[:40]}
    return False, {"error": "Unknown staged kind '%s'." % kind[:20]}


def approve(sel="all"):
    """Apply staged records by id (or 'all'). Drifted records are refused
    and KEPT; successes are consumed."""
    recs = _read_pending()
    want = _sel_ids(recs, sel)
    approved = []
    failed = {}
    for r in recs:
        try:
            rid = int(r.get("id", -1))
        except Exception:
            continue
        if rid not in want:
            continue
        try:
            ok, info = _apply_record(r)
        except Exception as e:
            ok, info = False, {"error": "apply failed: %s" % str(e)[:100]}
        if ok:
            approved.append(rid)
            _remove_pending_file(rid)
        else:
            failed[str(rid)] = info.get("error", "apply failed")
    out = {"success": len(failed) == 0, "approved": approved, "failed": failed,
           "pending": list_pending()}
    if approved and not failed:
        out["message"] = "Approved %d skill write(s)." % len(approved)
    elif not approved and not failed:
        out["message"] = "Nothing pending."
    return out


def reject(sel="all"):
    """Drop staged records by id (or 'all')."""
    recs = _read_pending()
    want = _sel_ids(recs, sel)
    dropped = []
    for r in recs:
        try:
            rid = int(r.get("id", -1))
        except Exception:
            continue
        if rid in want:
            dropped.append(rid)
            _remove_pending_file(rid)
    missing = [x for x in want if x not in dropped]
    out = {"success": True, "rejected": dropped, "pending": list_pending()}
    if missing:
        out["not_found"] = missing
    return out


# ---------- mutations ----------

def _validate_new_content(content):
    """(content, desc, warnings, err). Shared by create/propose/patch."""
    content = _norm_content(content)
    if not content.strip():
        return "", "", [], "content is required"
    err = _size_error(content)
    if err:
        return "", "", [], err
    desc, derr = parse_desc(content)
    if derr:
        return "", "", [], derr
    err = scan(content)
    if err:
        return "", "", [], err
    return content, desc, section_warnings(content), ""


def create(name, content):
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    content, desc, warns, verr = _validate_new_content(content)
    if verr:
        return {"success": False, "error": verr}
    if _read_file(_path_for(s), 1) is not None:
        return {"success": False,
                "error": "skill '%s' already exists; use patch to edit it" % s[:40]}
    if len(_list_names()) >= SKILL_MAX_COUNT:
        return {"success": False,
                "error": "skill store full (%d max); delete one first" % SKILL_MAX_COUNT}
    if approval_enabled():
        r = _stage("create", s, content, "", "")
        r["warnings"] = warns
        return r
    try:
        _write_skill(s, content)
    except OSError as e:
        return {"success": False, "error": "write failed: %s" % str(e)[:80]}
    out = {"success": True, "message": "Skill '%s' created." % s[:40], "name": s}
    if warns:
        out["warnings"] = warns
    return out


def propose(name, content):
    """/learn path: ALWAYS staged (even with approval off). Staged drafts
    are not loadable until approved."""
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    content, desc, warns, verr = _validate_new_content(content)
    if verr:
        return {"success": False, "error": verr}
    if _read_file(_path_for(s), 1) is not None:
        return {"success": False,
                "error": "skill '%s' already exists; propose a patch instead" % s[:40]}
    if len(_list_names()) >= SKILL_MAX_COUNT:
        return {"success": False,
                "error": "skill store full (%d max); delete one first" % SKILL_MAX_COUNT}
    r = _stage("propose", s, content, "", "")
    r["warnings"] = warns
    return r


def patch(name, old_text, new_text):
    """Targeted patch: old_text must occur exactly once in the file."""
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    try:
        old = str(old_text or "")
        new = str(new_text or "")
    except Exception:
        return {"success": False, "error": "old/new text required"}
    if not old:
        return {"success": False,
                "error": ("'patch' needs old_text - a short unique substring of the skill. "
                          "Reissue with old_text copied verbatim from the file.")}
    if not new:
        return {"success": False, "error": "new text is required for 'patch'."}
    cur = _read_file(_path_for(s), SKILL_MAX_BYTES + 1)
    if cur is None:
        return {"success": False, "error": "unknown skill '%s'" % s[:40]}
    n = cur.count(old)
    if n == 0:
        return {"success": False,
                "error": ("No match for '%s' in skill '%s'. Copy old_text verbatim "
                          "from skill_view output." % (old[:60], s[:40]))}
    if n > 1:
        return {"success": False,
                "error": ("'%s' appears %d times in skill '%s'. Include more surrounding "
                          "text so old_text occurs once." % (old[:60], n, s[:40]))}
    after = _norm_content(cur.replace(old, new, 1))
    if after == cur:
        return {"success": False, "error": "Patch is a no-op."}
    err = _size_error(after)
    if err:
        return {"success": False, "error": err}
    _, derr = parse_desc(after)
    if derr:
        return {"success": False, "error": "patched skill " + derr}
    err = scan(after)
    if err:
        return {"success": False, "error": err}
    warns = section_warnings(after)
    if approval_enabled():
        r = _stage("patch", s, after, old, _hash8(cur))
        r["warnings"] = warns
        return r
    try:
        _write_skill(s, after)
    except OSError as e:
        return {"success": False, "error": "write failed: %s" % str(e)[:80]}
    out = {"success": True, "message": "Skill '%s' patched." % s[:40], "name": s}
    if warns:
        out["warnings"] = warns
    return out


def delete(name):
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    cur = _read_file(_path_for(s), SKILL_MAX_BYTES + 1)
    if cur is None:
        return {"success": False, "error": "unknown skill '%s'" % s[:40]}
    if approval_enabled():
        return _stage("delete", s, "", "", _hash8(cur))
    try:
        _delete_skill(s)
    except OSError as e:
        return {"success": False, "error": "delete failed: %s" % str(e)[:80]}
    return {"success": True, "message": "Skill '%s' deleted." % s[:40]}


# ---------- bundles ----------

def _load_bundles():
    try:
        with open(BUNDLES_PATH, "r") as f:
            d = json.loads(f.read(8192) or "{}")
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        try:
            name = str(k).strip()
        except Exception:
            continue
        if _name_error(name) or not isinstance(v, list):
            continue
        members = []
        for m in v:
            try:
                ms = str(m).strip()
            except Exception:
                continue
            if not _name_error(ms):
                members.append(ms)
        out[name] = members
    return out


def list_bundles():
    """Sorted bundle names (never raises)."""
    try:
        names = list(_load_bundles().keys())
    except Exception:
        return []
    try:
        names.sort()
    except Exception:
        pass
    return names


def expand_bundle(name):
    """Concatenated skill bodies. Missing skills are skipped + noted in
    'missing' — never fatal (even all-missing still succeeds)."""
    err = _name_error(name)
    if err:
        return {"success": False, "error": err}
    s = str(name).strip()
    bundles = _load_bundles()
    if s not in bundles:
        avail = list_bundles()
        err = "unknown bundle '%s'" % s[:40]
        if avail:
            err += ". Available: " + ", ".join(avail[:12])
        return {"success": False, "error": err}
    found = []
    missing = []
    parts = ["# bundle: " + s]
    for member in bundles[s]:
        t = _read_file(_path_for(member), SKILL_MAX_BYTES + 1)
        if t is None:
            missing.append(member)
            continue
        found.append(member)
        parts.append("## " + member + "\n" + t[:SKILL_MAX_BYTES])
    return {"success": True, "bundle": s, "skills": found,
            "missing": missing, "content": "\n\n".join(parts)}
