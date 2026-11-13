# agent_tools.py — device tools glue + LittleFS memory/log, pins, prompt.
# MicroPython port of src/agent_tools.h/.cpp.
try:
    import ujson as json
except ImportError:
    import json

try:
    import gc
except ImportError:
    gc = None

# The active conversation. sessions.ensure_store() repoints this at
# opt/data/sessions/<id>.jsonl on boot (legacy boards migrate their single
# chatlog.jsonl into that store); it stays a module global because status,
# backup, doctor and the host tests all treat it as "the current chat log".
LOG_PATH = "opt/data/chatlog.jsonl"
MEM_PATH = "opt/data/memory.txt"
# Cron / autonomous events. Deliberately NOT a session: keeping job output
# out of conversations stops it being listed as a chat and being injected as
# fake user/assistant history on the next web turn.
ACTIVITY_MAX_BYTES = 131072  # 128 KB
ACTIVITY_KEEP_BYTES = 65536  # keep newest 64 KB
# Rolling chat log budget. 320 KB is ~1.6% of the 16 MB flash and holds a
# 20-turn conversation even when every message hits the default 4000-char
# cap (40 messages x 4000 = 160 KB + JSON overhead). Rotation keeps the
# newest 200 KB, which still fits 20 max-cap turns.
LOG_MAX_BYTES = 327680
LOG_KEEP_BYTES = 204800
# Legacy alias of the device-store cap; memory.py owns the caps now.
MEM_MAX_BYTES = 2200

# Filled by tools/registry.py import (avoids circular import at module load).
TOOL_REGISTRY = []
TOOL_COUNT = 0
gFsOk = True
gRestartPending = False

# Phase 6 delegation: when not None, only these tool names may run via
# execTool (child-turn restriction set by delegate.py, always restored via
# try/finally). Parent turns leave it None (no restriction).
_ACTIVE_TOOL_ALLOW = None

# D3 usage counters: per-tool execution counts (RAM dict, reset on boot).
# Incremented once per execTool call — execTool is the single choke point
# for every tool execution (chat turns, cron run_now, Telegram turns).
_TOOL_CALL_COUNTS = {}


def _fs_size(path):
    try:
        import os
        s = os.stat(path)
        # os.stat returns tuple (mode, ino, dev, nlink, uid, gid, size, ...)
        return s[6]
    except Exception:
        return 0


def active_log_path():
    """The conversation file new turns belong to.

    Resolved on every call from the session store (opt/data/sessions/<id>),
    never cached in a module global: a cached path survives a chdir/flash
    remount and silently points at the wrong conversation. LOG_PATH stays the
    legacy default for a board whose store cannot be read.
    """
    try:
        import sessions
        return sessions.active_path()
    except Exception:
        return LOG_PATH


def initAgentFS():
    global gFsOk
    # MicroPython mounts flash automatically; ensure the user-data home
    # (opt/data + workspace) exists and migrate pre-split root state once.
    try:
        import fsutil as _fs
        try:
            _fs.ensure_data_tree()
        except Exception as e:
            print("[fs] data tree:", e)
    except Exception:
        pass
    # Session store: mkdir opt/data/sessions, migrate a legacy single log,
    # and repoint LOG_PATH at the active conversation. Best-effort.
    try:
        import sessions as _sess
        _sess.ensure_store()
    except Exception as e:
        print("[fs] session store:", str(e)[:60])
    try:
        with open(MEM_PATH, "a"):
            pass
        gFsOk = True
    except Exception as e:
        print("[fs] FAIL", e)
        gFsOk = False
    print("[fs] ok" if gFsOk else "[fs] FAIL")
    return gFsOk


def toolIndex(name):
    for i, t in enumerate(TOOL_REGISTRY):
        if t["name"] == name:
            return i
    return -1


def toolEnabled(name):
    import config
    i = toolIndex(name)
    if i < 0:
        return False
    return bool((config.gToolsMask >> i) & 1)


def toolEnabledIdx(i):
    import config
    return bool((config.gToolsMask >> i) & 1)


def all_tools_mask():
    n = len(TOOL_REGISTRY)
    if n >= 32:
        return 0xFFFFFFFF
    if n == 0:
        return 0
    return (1 << n) - 1


def toolNameAt(i):
    if 0 <= i < len(TOOL_REGISTRY):
        return TOOL_REGISTRY[i]["name"]
    return ""


def toolUiHintAt(i):
    if 0 <= i < len(TOOL_REGISTRY):
        return TOOL_REGISTRY[i].get("ui_hint", "")
    return ""


def toolDescriptionAt(i):
    if 0 <= i < len(TOOL_REGISTRY):
        return TOOL_REGISTRY[i].get("description", "")
    return ""


def readMemoryFacts():
    # Compat shim over memory.py (device store), which owns the files.
    try:
        import memory as _mem
        return _mem.read_text("device")
    except Exception:
        return ""


def appendMemoryFact(text):
    # Compat shim over memory.py (device store add). Returns True on
    # success, exact-duplicate, or approval-staged writes.
    try:
        import memory as _mem
        r = _mem.add("device", text)
        return bool(r.get("success"))
    except Exception:
        return False


def _chat_entry_chars():
    """Per-message cap for chatlog.jsonl (Config page: chat history)."""
    try:
        import config
        return int(getattr(config, "cfgChatEntryChars",
                           config.DEFAULT_CHAT_ENTRY_CHARS))
    except Exception:
        return 4000


def _log_budgets():
    """(rotate_at_bytes, keep_bytes) from Config -> Chat history."""
    try:
        import config
        m = int(getattr(config, "cfgChatLogMaxKB", LOG_MAX_BYTES // 1024))
        k = int(getattr(config, "cfgChatLogKeepKB", LOG_KEEP_BYTES // 1024))
        return m * 1024, k * 1024
    except Exception:
        return LOG_MAX_BYTES, LOG_KEEP_BYTES


def _rotate_chatlog(max_bytes, keep_bytes, path=None, block=16384):
    """Trim one log to its newest keep_bytes, block by block.

    The old rotation did `f.read()` of the whole log and then wrote a slice
    back. That is fine at 32 KB but not once the log can be hundreds of KB
    (or live on USB storage): peak RAM would be the log plus the slice. This
    copies the tail through a temp file in fixed-size blocks, then swaps it
    in, so RAM stays flat at one block.
    """
    import os
    p = path or active_log_path()
    try:
        sz = _fs_size(p)
    except Exception:
        return
    if sz <= max_bytes:
        return
    start = sz - keep_bytes
    if start < 0:
        start = 0
    tmp = p + ".tmp"
    wrote = 0
    try:
        with open(p, "rb") as src:
            with open(tmp, "wb") as dst:
                src.seek(start)
                if start > 0:
                    # Drop the partial first line produced by the byte offset.
                    while True:
                        b = src.read(block)
                        if not b:
                            break
                        i = b.find(b"\n")
                        if i >= 0:
                            tail = b[i + 1:]
                            if tail:
                                dst.write(tail)
                                wrote += len(tail)
                            break
                while True:
                    b = src.read(block)
                    if not b:
                        break
                    dst.write(b)
                    wrote += len(b)
        if wrote:
            try:
                os.remove(p)
            except OSError:
                pass
            os.rename(tmp, p)
        else:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def appendChatLog(user, asst, path=None, max_b=None, keep_b=None):
    # one open/close per turn, minimal flash wear
    p = path or active_log_path()
    cap = _chat_entry_chars()
    try:
        import fsutil as _fs
        try:
            _fs.ensure_data_tree()
        except Exception:
            pass
    except Exception:
        pass
    try:
        if max_b is None or keep_b is None:
            _mb, _kb = _log_budgets()
            max_b = _mb if max_b is None else max_b
            keep_b = _kb if keep_b is None else keep_b
        if _fs_size(p) > max_b:
            _rotate_chatlog(max_b, keep_b, p)
    except Exception:
        pass
    try:
        with open(p, "a") as f:
            f.write(json.dumps({"r": "user", "c": (user or "")[:cap]}) + "\n")
            f.write(json.dumps({"r": "assistant", "c": (asst or "")[:cap]}) + "\n")
    except OSError:
        return False
    return True


def appendActivity(user, asst):
    """Log an autonomous event (cron run, system notice) outside sessions.

    Same append-only shape as a chat turn so the log stays readable, but with
    its own smaller budget and a path no conversation reads or lists.
    """
    try:
        import sessions as _sess
        p = _sess.ACTIVITY_PATH
    except Exception:
        p = "opt/data/activity.jsonl"
    return appendChatLog(user, asst, path=p,
                         max_b=ACTIVITY_MAX_BYTES, keep_b=ACTIVITY_KEEP_BYTES)


def injectRecentLog(msgs, curUser, maxMsgs=8, path=None):
    """Append last N persisted turns to msgs list. Returns count added.

    Reads the ACTIVE session only (last-8). It is intentionally NOT
    cross-session recall — facts from other conversations are found via
    sessions.search() (session_search tool / GET /api/memory?q=...).

    Uses the shared chunked tail reader: only the last few lines are read, so
    this fallback stays cheap even when the rolling log is large."""
    p = path or active_log_path()
    try:
        import fsutil
        entries, _ = fsutil.read_jsonl_tail(p, maxMsgs)
    except Exception:
        return 0
    added = 0
    for d in entries:
        r = d.get("r", "")
        c = d.get("c", "")
        if not r or not c:
            continue
        if r == "user" and c == curUser:
            continue
        msgs.append({"role": r, "content": c[:1500]})
        added += 1
    return added


# ---- pins: S3-primary, classic-ESP32 compatible ----
_WRITE_CLASSIC = {2, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33}
_READ_EXTRA_CLASSIC = {34, 35, 36, 39}
_ADC_CLASSIC = {32, 33, 34, 35, 36, 39}
# ESP32-S3: GPIO 0-21 + 35-48 exist. 19/20 = USB-JTAG, 26-32 = SPI flash/PSRAM.
_WRITE_S3 = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 21,
             35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48}
_READ_EXTRA_S3 = set()  # all writable are readable; input-only below
_READ_ONLY_S3 = set()
_ADC_S3 = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}


def _is_s3():
    try:
        import os
        m = " ".join(str(x) for x in os.uname()).upper()
        if "S3" in m:
            return True
    except Exception:
        pass
    return False


def pinCanWrite(p):
    try:
        p = int(p)
    except Exception:
        return False
    if _is_s3():
        return p in _WRITE_S3
    return p in _WRITE_CLASSIC or p in _WRITE_S3


def pinCanRead(p):
    try:
        p = int(p)
    except Exception:
        return False
    if pinCanWrite(p):
        return True
    if _is_s3():
        return p in _READ_ONLY_S3
    return p in _READ_EXTRA_CLASSIC


def pinCanADC(p):
    try:
        p = int(p)
    except Exception:
        return False
    # union so both chip families work; run() validates per-board
    return (p in _ADC_CLASSIC) or (p in _ADC_S3)


def _live_snapshot():
    ip, uptime_s, heap, rssi = "ap", 0, 0, 0
    try:
        import time
        uptime_s = int(time.ticks_ms() // 1000) if hasattr(time, "ticks_ms") else 0
    except Exception:
        pass
    try:
        if gc is not None and hasattr(gc, "mem_free"):
            heap = gc.mem_free()
    except Exception:
        pass
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        if sta.isconnected():
            try:
                ip = sta.ifconfig()[0]
            except Exception:
                ip = "sta"
            try:
                rssi = sta.status("rssi")
            except Exception:
                try:
                    rssi = sta.status()
                except Exception:
                    rssi = 0
    except Exception:
        pass
    return ip, uptime_s, heap, rssi


def buildSystemPrompt():
    import config
    parts = ["You are Talaria Agent, an assistant running on an ESP32-S3 board at talaria-agent.local. "
             "Reply in plain text. "]
    names = [t["name"] for i, t in enumerate(TOOL_REGISTRY) if toolEnabledIdx(i)]
    if names:
        parts.append("Enabled device tools: " + ", ".join(names) + ". ")
        if "run_script" in names:
            parts.append("Scripts you write under workspace/ run on the device "
                         "via run_script and may import the device's own "
                         "modules. ")
    else:
        parts.append("Enabled device tools: (none). ")
    # The model would otherwise read "device agent + web_fetch tool" as
    # "I am a shell with no knowledge" and answer "I can't, I have no offline
    # knowledge" to ordinary questions. It has full general knowledge; say so.
    parts.append("You have full general knowledge. Answer ordinary questions "
                 "(history, geography, science, code, maths, explanations) "
                 "directly and completely from your own knowledge, without "
                 "calling a tool. Never reply that you lack knowledge or that "
                 "you can only look things up on the web. ")
    parts.append("Use a tool ONLY when the request needs live device state "
                 "(pins, GPIO, ADC, wifi, memory, restart), saved procedures, "
                 "scheduled work, or fresh internet "
                 "data. Never guess pin levels or current events. ")
    parts.append("Workspace files live under opt/data/workspace/ (shown as "
                 "/workspace/ in Files) and can be read, searched and edited "
                 "with the read_file, search_files, write_file and patch_file "
                 "tools (a .bak checkpoint is kept before each write). When "
                 "creating scripts or files, ALWAYS write under "
                 "opt/data/workspace/ — never to the flash root or other "
                 "locations. ")
    parts.append("When the user asks to save a procedure as a reusable skill, "
                 "draft the full skill text and call skills with action "
                 "create (or propose for a /learn draft, patch/delete to revise): "
                 "writes are quarantine-scanned and, with write-approval on, "
                 "STAGED for human approval in Skills — tell the user to approve "
                 "there. When the user wants something done on a schedule, use "
                 "the cron tool (add/list/edit/pause/resume/remove/run_now, max 5 "
                 "jobs, every 60s..86400s) and confirm the schedule back. "
                 "Cron jobs can also run a workspace script: pass script "
                 "(e.g. workspace/hello.py) with no_agent=true to run the script "
                 "instead of an agent turn, delivering stdout verbatim. ")
    parts.append("Keep chat and acknowledgements short, but give a real, "
                 "complete answer when the user asks a substantive question. "
                 "Always finish with a plain-text reply summarizing tool "
                 "results (never leave the reply empty after tools).")
    try:
        mem = readMemoryFacts()
    except Exception:
        mem = ""
    if mem:
        parts.append("\nLong-term memory:\n" + mem[:1200])
    ip, up, heap, rssi = _live_snapshot()
    parts.append(" [dev ip=%s up=%ds heap=%d rssi=%s]" % (ip, up, heap, rssi))
    return "".join(parts)


def addToolsArray(req):
    """Mutate OpenAI-compatible req dict: req['tools'] = [...] for enabled tools."""
    tools = []
    for i, t in enumerate(TOOL_REGISTRY):
        if not toolEnabledIdx(i):
            continue
        if _ACTIVE_TOOL_ALLOW is not None and \
                t["name"] not in _ACTIVE_TOOL_ALLOW:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    if tools:
        req["tools"] = tools
        req["tool_choice"] = "auto"
    return req


def execTool(name, args):
    try:
        _TOOL_CALL_COUNTS[name] = _TOOL_CALL_COUNTS.get(name, 0) + 1
    except Exception:
        pass
    if args is None:
        args = {}
    for t in TOOL_REGISTRY:
        if t["name"] == name:
            if _ACTIVE_TOOL_ALLOW is not None and \
                    name not in _ACTIVE_TOOL_ALLOW:
                return '{"error":"tool not allowed in this delegated turn"}'
            try:
                s = t["run"](args if isinstance(args, dict) else {})
            except Exception as e:
                s = json.dumps({"error": "tool exception: %s" % str(e)[:120]})
            cap = t.get("max_result_chars", 1200) or 1200
            if len(s) > cap:
                s = s[:cap]
            return s
    return '{"error":"unknown tool"}'
