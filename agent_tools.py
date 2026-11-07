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
LOG_MAX_BYTES = 32768
MEM_MAX_BYTES = 4096

# Filled by tools/registry.py import (avoids circular import at module load).
TOOL_REGISTRY = []
TOOL_COUNT = 0
gFsOk = True
gRestartPending = False


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
    try:
        with open(MEM_PATH, "r") as f:
            s = f.read()
    except OSError:
        return ""
    if len(s) > MEM_MAX_BYTES:
        s = s[len(s) - MEM_MAX_BYTES:]
    return s


def appendMemoryFact(text):
    if not text:
        return False
    cur = readMemoryFacts()
    line = text.strip().replace("\n", " ")
    if len(line) > 500:
        line = line[:500]
    if not line:
        return False
    cur += "- " + line + "\n"
    while len(cur) > MEM_MAX_BYTES:
        nl = cur.find("\n")
        if nl < 0:
            cur = cur[len(cur) - MEM_MAX_BYTES:]
            break
        cur = cur[nl + 1:]
    try:
        with open(MEM_PATH, "w") as f:
            f.write(cur)
    except OSError:
        return False
    return True


def appendChatLog(user, asst):
    # one open/close per turn, minimal flash wear
    try:
        sz = _fs_size(LOG_PATH)
        if sz > LOG_MAX_BYTES:
            try:
                with open(LOG_PATH, "r") as r:
                    all_text = r.read()
            except OSError:
                all_text = ""
            if len(all_text) > 16384:
                all_text = all_text[len(all_text) - 16384:]
            nl = all_text.find("\n")
            if nl >= 0:
                all_text = all_text[nl + 1:]
            with open(LOG_PATH, "w") as w:
                w.write(all_text)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({"r": "user", "c": (user or "")[:1500]}) + "\n")
            f.write(json.dumps({"r": "assistant", "c": (asst or "")[:1500]}) + "\n")
    except OSError:
        return False
    return True


def injectRecentLog(msgs, curUser, maxMsgs=8):
    """Append last N persisted turns to msgs list. Returns count added."""
    try:
        with open(LOG_PATH, "r") as f:
            all_text = f.read()
    except OSError:
        return 0
    lines = all_text.split("\n")
    # count non-empty for start calc
    total = sum(1 for ln in lines if ln.strip())
    start = total - maxMsgs if total > maxMsgs else 0
    added = 0
    idx = 0
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if idx < start:
            idx += 1
            continue
        idx += 1
        try:
            d = json.loads(s)
        except Exception:
            continue
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
    if args is None:
        args = {}
    for t in TOOL_REGISTRY:
        if t["name"] == name:
            try:
                s = t["run"](args if isinstance(args, dict) else {})
            except Exception as e:
                s = json.dumps({"error": "tool exception: %s" % str(e)[:120]})
            cap = t.get("max_result_chars", 1200) or 1200
            if len(s) > cap:
                s = s[:cap]
            return s
    return '{"error":"unknown tool"}'
