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

LOG_PATH = "chatlog.jsonl"
MEM_PATH = "memory.txt"
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


def initAgentFS():
    global gFsOk
    # MicroPython mounts flash automatically; just probe writability.
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


def _rotate_chatlog(max_bytes, keep_bytes, block=16384):
    """Trim the log to its newest keep_bytes, block by block.

    The old rotation did `f.read()` of the whole log and then wrote a slice
    back. That is fine at 32 KB but not once the log can be hundreds of KB
    (or live on USB storage): peak RAM would be the log plus the slice. This
    copies the tail through a temp file in fixed-size blocks, then swaps it
    in, so RAM stays flat at one block.
    """
    import os
    try:
        sz = _fs_size(LOG_PATH)
    except Exception:
        return
    if sz <= max_bytes:
        return
    start = sz - keep_bytes
    if start < 0:
        start = 0
    tmp = LOG_PATH + ".tmp"
    wrote = 0
    try:
        with open(LOG_PATH, "rb") as src:
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
                os.remove(LOG_PATH)
            except OSError:
                pass
            os.rename(tmp, LOG_PATH)
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


def appendChatLog(user, asst):
    # one open/close per turn, minimal flash wear
    cap = _chat_entry_chars()
    try:
        max_b, keep_b = _log_budgets()
        if _fs_size(LOG_PATH) > max_b:
            _rotate_chatlog(max_b, keep_b)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({"r": "user", "c": (user or "")[:cap]}) + "\n")
            f.write(json.dumps({"r": "assistant", "c": (asst or "")[:cap]}) + "\n")
    except OSError:
        return False
    return True


def injectRecentLog(msgs, curUser, maxMsgs=8):
    """Append last N persisted turns to msgs list. Returns count added.

    Phase 4 note: this reads the CURRENT chatlog.jsonl only (last-8). It is
    intentionally NOT cross-rotation recall — pre-/new history is found via
    sessions.search() (session_search tool / GET /api/memory?q=...).

    Uses the shared chunked tail reader: only the last few lines are read, so
    this fallback stays cheap even when the rolling log is large."""
    try:
        import fsutil
        entries, _ = fsutil.read_jsonl_tail(LOG_PATH, maxMsgs)
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
    parts = ["You are ESP32-Agent, an assistant running on an ESP32-S3 board at esp32-agent.local. "
             "Reply in plain text. "]
    names = [t["name"] for i, t in enumerate(TOOL_REGISTRY) if toolEnabledIdx(i)]
    if names:
        parts.append("Enabled device tools: " + ", ".join(names) + ". ")
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
                 "(pins, GPIO, ADC, wifi, memory, restart) or fresh internet "
                 "data. Never guess pin levels or current events. ")
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
