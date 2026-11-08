# server.py — Microdot app with all pages + JSON APIs.
# MicroPython port of src/routes.cpp (setupRoutes + handlers).
try:
    import ujson as json
except ImportError:
    import json

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import logbuf
    logbuf.install()  # keep serial print() mirrored while serving
except Exception:
    pass

_ap_scan_cache = {"body": "", "at": 0}
_models_cache = {"body": "", "at": 0, "ep": ""}

# ---------- D3 usage counters (RAM only; reset on (re)boot) ----------
# turns_since_boot: chat turns served since boot (POST /api/chat turns plus
# /api/chat-stream responses; a streamed turn that yields need_tools falls
# back to /api/chat for the tool loop and counts twice — once per request).
# tool_calls lives in agent_tools._TOOL_CALL_COUNTS (execTool is the single
# choke point for every tool execution). last_chat_ms: wall time around the
# chat turn in the server handler. last_upstream_ms: wall time around the
# upstream LLM call; None (JSON null) until the first LLM-backed turn —
# validation/busy/offline rejections never touch it. All updates are
# guarded so instrumentation can never break a chat turn.

_STATS_TURNS_SINCE_BOOT = 0
_STATS_LAST_CHAT_MS = 0
_STATS_LAST_UPSTREAM_MS = None


def _stats_note_turn(chat_ms, upstream_ms=None):
    """Record one chat turn's timings. Never raises."""
    global _STATS_TURNS_SINCE_BOOT, _STATS_LAST_CHAT_MS, _STATS_LAST_UPSTREAM_MS
    try:
        _STATS_TURNS_SINCE_BOOT = int(_STATS_TURNS_SINCE_BOOT) + 1
    except Exception:
        try:
            _STATS_TURNS_SINCE_BOOT = 1
        except Exception:
            pass
    try:
        _STATS_LAST_CHAT_MS = int(chat_ms)
    except Exception:
        pass
    try:
        if upstream_ms is not None:
            _STATS_LAST_UPSTREAM_MS = int(upstream_ms)
    except Exception:
        pass


_MODELS_MAX_IDS = 200
_MODELS_MAX_BYTES = 131072

# ---------- dashboard login ----------
# The SPA signs in with a fixed username ("admin") plus the device auth token
# as the password — the Hermes-style login screen over the existing Bearer
# mechanism (the device has no cookie/session store, so POST /api/login is a
# stateless verifier: the browser keeps sending the token as the Bearer).
LOGIN_USERNAME = "admin"


def _verify_login(username, password):
    """Check a username+password pair against the device auth token.

    Username match is case-insensitive and forgiving of whitespace; the
    password must equal config.cfgAuthToken exactly (after stripping). When
    auth is disabled (AP mode or no token configured) any admin login
    succeeds so an open device can never lock its owner out. Never raises —
    failures return False. Pure enough for host tests (imports config/net).
    """
    try:
        u = str(username or "").strip().lower()
    except Exception:
        return False
    if u != LOGIN_USERNAME:
        return False
    try:
        p = str(password or "").strip()
    except Exception:
        return False
    try:
        import net as _net
        if bool(getattr(_net, "apMode", False)):
            return True
    except Exception:
        pass
    try:
        import config as _cfg
        token = str(getattr(_cfg, "cfgAuthToken", "") or "")
    except Exception:
        return False
    if not token:
        return True
    return bool(p) and p == token

# ---------- file manager (Explorer) helpers ----------
# Canonical implementations live in fsutil.py (shared with the Phase 7 file
# tools and checkpoint.py). These thin wrappers keep the historic server._fs_*
# names/signatures (host tests use them) plus the server-local _FS_ROOT
# override, which is passed through explicitly on every call.
#
# User-data home (Hermes parity): `/api/files` is LOCKED to _DATA_ROOT
# (opt/data); system code at flash `/` is only reachable via the separate
# `/api/system/files/*` repair hatch. Low-level _fs_* helpers stay
# full-flash on purpose — the lock lives in the route layer (_files_data_norm)
# so tests and the system hatch keep direct access.
_FS_ROOT = ""
_FS_MAX_READ = 100000
_FS_MAX_WRITE = 200000
_DATA_ROOT = "opt/data"
_DATA_WORKSPACE = "opt/data/workspace"


def _fsu():
    import fsutil as _m
    return _m


def _fs_norm(p):
    return _fsu().norm(p)


def _fs_full(norm):
    return _fsu().full(norm, _FS_ROOT)


def _fs_parent(norm):
    return _fsu().parent(norm)


def _fs_is_dir(full):
    return _fsu().is_dir(full)


def _fs_stat_size(full):
    return _fsu().stat_size(full)


def _fs_stat_mtime(full):
    return _fsu().stat_mtime(full)


def _fs_list_dir(norm):
    """Return (entries, err). entries=[{name,path,is_dir,size,mtime}]."""
    return _fsu().list_dir(norm, _FS_ROOT)


def _fs_read_text(norm, max_bytes=_FS_MAX_READ):
    return _fsu().read_text(norm, max_bytes, _FS_ROOT)


def _fs_ensure_parent(norm):
    """mkdir -p the parent chain of norm. Returns '' or err text."""
    return _fsu().ensure_parent(norm, _FS_ROOT)


def _fs_write_text(norm, content, max_bytes=_FS_MAX_WRITE):
    return _fsu().write_text(norm, content, max_bytes, _FS_ROOT)


def _fs_delete(norm):
    """Delete a file or directory tree. Refuses root. Returns '' or err."""
    return _fsu().delete(norm, _FS_ROOT)


def _files_data_norm(norm):
    """Map a Files-API norm into the locked data home, or None if invalid.

    '' (root) -> _DATA_ROOT; an already-data path passes through; anything
    else is treated as relative to the data home so flash `/` is never
    addressable through `/api/files`. Mirrors Hermes locked_root.
    """
    if norm is None:
        return None
    try:
        if not norm:
            return _DATA_ROOT
        if norm == _DATA_ROOT or norm.startswith(_DATA_ROOT + "/"):
            return norm
        return _DATA_ROOT + "/" + norm
    except Exception:
        return None


def _files_data_parent(dnorm):
    """Parent display path for a data norm, or None at the data root."""
    try:
        if not dnorm or dnorm == _DATA_ROOT:
            return None
        p = _fs_parent(dnorm)
        if p == _DATA_ROOT or p.startswith(_DATA_ROOT + "/"):
            return "/" + p
        return None
    except Exception:
        return None


def _ensure_data_tree_best_effort():
    """mkdir -p opt/data + workspace so the locked root always lists."""
    try:
        _fsu().ensure_data_tree(_FS_ROOT)
    except Exception:
        pass


def _split_url(url):
    u = (url or "").strip()
    is_https = u.startswith("https://")
    if is_https:
        rest = u[8:]
    elif u.startswith("http://"):
        rest = u[7:]
    else:
        rest = u
    slash = rest.find("/")
    if slash < 0:
        host, path = rest, "/"
    else:
        host, path = rest[:slash], rest[slash:]
    port = 443 if is_https else 80
    if ":" in host:
        h, p = host.rsplit(":", 1)
        try:
            port = int(p)
            host = h
        except Exception:
            pass
    if not host:
        raise ValueError("empty host")
    return is_https, host, port, path or "/"


def _scan_model_ids(chunks, max_ids=_MODELS_MAX_IDS):
    """Incremental '"id"' scanner over text chunks. Returns list of ids.

    Pure function (no sockets) so it runs on CPython tests too. Mirrors the
    C++ streaming scan: 600-char sliding window, stops at max_ids.
    """
    ids = []
    win = ""
    in_data = False
    for ch in chunks:
        if len(ids) >= max_ids:
            break
        if ch:
            win += ch
        if len(win) > 600:
            win = win[-600:]
        if not in_data:
            if '"data"' not in win:
                continue
            in_data = True
        while len(ids) < max_ids:
            p = win.find('"id"')
            if p < 0:
                break
            q = p + 4
            while q < len(win) and win[q] in (" ", "\t"):
                q += 1
            if q >= len(win) or win[q] != ":":
                break  # split across chunks: wait for more
            q += 1
            while q < len(win) and win[q] in (" ", "\t"):
                q += 1
            if q >= len(win) or win[q] != '"':
                break
            e = win.find('"', q + 1)
            if e < 0:
                break
            mid = win[q + 1:e]
            win = win[e + 1:]
            if mid and len(mid) <= 160:
                ids.append(mid)
    return ids


def _read_log_tail(path, max_lines=10, max_chars=None, block_bytes=16384):
    """Return (entries, bytes) for the last max_lines entries of the chat log.

    entries = [{"role": "user"|"assistant", "content": str}]. Shared by
    GET /api/memory (tail=N), the chat page's transcript restore, and the
    prompt's recent-history fallback (via fsutil.read_jsonl_tail).

    fsutil.read_jsonl_tail reads backwards in fixed-size blocks and parses only
    the lines it needs, so RAM/time scale with the requested tail rather than
    the log size — important once the log is hundreds of KB (or on USB later).

    max_chars defaults to config.cfgChatEntryChars (Config -> Chat history);
    the old hard cap of 800 was what cut long replies to ~2 paragraphs on
    reload.
    """
    if max_chars is None:
        try:
            import config
            max_chars = int(getattr(config, "cfgChatEntryChars",
                                    config.DEFAULT_CHAT_ENTRY_CHARS))
        except Exception:
            max_chars = 4000
    try:
        import fsutil
        raw, total = fsutil.read_jsonl_tail(path, max_lines, block_bytes)
    except Exception:
        return [], 0
    out = []
    for e in raw:
        r = str(e.get("r", ""))[:20]
        c = str(e.get("c", ""))
        if not r or not c:
            continue
        out.append({"role": r, "content": c[:max_chars]})
    return out, total


def _resolve_session(raw, activate=False):
    """(session id, log path) for a request.

    A blank or unusable id means "whatever the web UI had open" (active.json).
    `activate` persists that choice, which is what makes a reload / a shared
    link land in the same conversation. Never raises: a broken store falls
    back to agent_tools.LOG_PATH so chat keeps working.
    """
    try:
        import sessions as _sess
        sid = _sess.safe_id(raw)
        if not sid:
            sid = _sess.active_id()
        elif activate:
            _sess.set_active(sid)
        return sid, _sess.path_for(sid)
    except Exception:
        try:
            import agent_tools as _at
            return "", _at.active_log_path()
        except Exception:
            return "", ""


def _resolve_ipv4(host, port):
    """connect() sockaddr for host, preferring IPv4 (see llm._resolve_ipv4)."""
    addrs = _resolve_all_ipv4(host, port)
    if not addrs:
        raise ValueError("no address for %s" % host)
    return addrs[0]


def _resolve_all_ipv4(host, port):
    """All IPv4 connect() sockaddrs for host (empty if none)."""
    import socket
    try:
        infos = socket.getaddrinfo(host, port)
    except Exception:
        return []
    return [i[4] for i in infos if i[0] == socket.AF_INET]


def _send_all(s, buf):
    """ussl.send() may partial-write — loop until all sent (see llm)."""
    if isinstance(buf, str):
        buf = buf.encode()
    mv = memoryview(buf)
    sent = 0
    while sent < len(buf):
        n = s.send(mv[sent:])
        if n is None:
            continue
        if n <= 0:
            raise OSError("send stalled")
        sent += n


def _fetch_models_stream(url, api_key):
    """Raw-socket GET with HTTP/1.0 (no chunked encoding), streamed id scan.

    Low RAM: 512B socket reads + 600-char window + short id list. Returns
    (True, [ids], 200) or (False, err_text, http_code_or_0).
    """
    try:
        is_https, host, port, path = _split_url(url)
    except Exception as e:
        return False, "bad url: %s" % str(e)[:80], 0
    try:
        import socket
    except ImportError:
        return False, "no socket", 0
    s = None
    last_err, last_code = "no attempt", 0
    for attempt in range(4):
        try:
            import gc
            try:
                gc.collect()
            except Exception:
                pass
            s = socket.socket()
            try:
                s.settimeout(10)
            except Exception:
                pass
            try:
                import llm as _llm
                _addrs = _llm._resolve_all_ipv4(host, port)
            except Exception:
                _addrs = _resolve_all_ipv4(host, port)
            if not _addrs:
                raise ValueError("no address for %s" % host)
            s.connect(_addrs[attempt % len(_addrs)])
            if is_https:
                # NOTE: MicroPython 1.29 has `ssl`, not `ussl`. Always pass
                # server_hostname: without SNI, SNI-routed edges never answer.
                # MicroPython: ssl.wrap_socket(direct). CPython 3.12+: removed,
                # use SSLContext instead.
                try:
                    import ssl as _sslmod
                except ImportError:
                    import ussl as _sslmod
                _wrap = getattr(_sslmod, "wrap_socket", None)
                if _wrap is not None:
                    try:
                        s = _wrap(s, server_hostname=host)
                    except TypeError:
                        s = _wrap(s)  # very old ussl without SNI
                else:
                    _ctx = _sslmod.create_default_context()
                    _ctx.check_hostname = False
                    _ctx.verify_mode = _sslmod.CERT_NONE
                    s = _ctx.wrap_socket(s, server_hostname=host)
                try:
                    s.settimeout(15)
                except Exception:
                    pass
            req = "GET %s HTTP/1.0\r\nHost: %s\r\nAccept: application/json\r\nConnection: close\r\n" % (path, host)
            if api_key:
                req += "Authorization: Bearer %s\r\n" % api_key
            req += "\r\n"
            _send_all(s, req)
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 8192:
                d = s.recv(512)
                if not d:
                    break
                buf += d
            if b"\r\n\r\n" not in buf:
                raise OSError("bad headers")
            head, rest = buf.split(b"\r\n\r\n", 1)
            try:
                code = int(head.split(b"\r\n", 1)[0].decode().split(" ")[1])
            except Exception:
                raise OSError("bad status")
            if code < 200 or code >= 300:
                return False, "upstream HTTP %d" % code, code

            def _gen(first):
                if first:
                    yield first.decode("utf-8", "ignore")
                total = len(first)
                while total < _MODELS_MAX_BYTES:
                    try:
                        d = s.recv(512)
                    except Exception:
                        break
                    if not d:
                        break
                    total += len(d)
                    yield d.decode("utf-8", "ignore")

            ids = _scan_model_ids(_gen(rest))
            if not ids:
                last_err, last_code = "no models parsed from endpoint", 502
            else:
                try:
                    s.close()
                except Exception:
                    pass
                s = None
                return True, ids, 200
        except Exception as e:
            last_err, last_code = "request failed: %s" % str(e)[:100], 0
        finally:
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
            s = None
    return False, last_err, last_code

_HEX = "0123456789abcdef"


def _hex2(n):
    # 2-char lowercase hex without %x (kept tiny for MicroPython %-support).
    try:
        n = int(n) & 0xFF
    except Exception:
        return "00"
    return _HEX[n >> 4] + _HEX[n & 15]


def _hexbytes(b):
    try:
        out = []
        for x in b:
            out.append(_hex2(x))
        return "".join(out)
    except Exception:
        return ""


def _macstr(b):
    try:
        parts = []
        for x in b:
            parts.append(_hex2(x))
        return ":".join(parts)
    except Exception:
        return ""


def _p2(n):
    try:
        n = int(n)
    except Exception:
        return "00"
    if n < 0:
        n = 0
    if n < 10:
        return "0" + str(n)
    return str(n)


def _collect_stats(do_i2c=False):
    """Best-effort device telemetry for GET /api/stats (and the /stats page).

    Every field is guarded: anything unavailable on a given build/CPU
    degrades to 0/"" so one missing sensor never breaks the page. Runs on
    CPython (host tests, via tests/stubs.py) as well as MicroPython.
    """
    s = {}
    try:
        import time as _t
        up = int(_t.ticks_ms() // 1000) if hasattr(_t, "ticks_ms") else 0
    except Exception:
        up = 0
    s["uptime_s"] = up
    try:
        _d = up // 86400
        _h = (up % 86400) // 3600
        _m = (up % 3600) // 60
        _ss = up % 60
        _p = []
        if _d:
            _p.append("%dd" % _d)
        if _h or _d:
            _p.append("%dh" % _h)
        if _m or _h or _d:
            _p.append("%dm" % _m)
        _p.append("%ds" % _ss)
        s["uptime_human"] = " ".join(_p)
    except Exception:
        s["uptime_human"] = ""
    # --- RAM (MicroPython GC heap) ---
    try:
        import gc as _gc
        _free = int(_gc.mem_free())
        try:
            _alloc = int(_gc.mem_alloc())
        except Exception:
            _alloc = 0
        s["ram_free"] = _free
        s["ram_alloc"] = _alloc
        s["ram_total"] = _free + _alloc
    except Exception:
        s["ram_free"] = 0
        s["ram_alloc"] = 0
        s["ram_total"] = 0
    # --- IDF heap regions (internal vs SPIRAM breakdown) ---
    try:
        import esp32 as _esp
        _regions = []
        try:
            _info = _esp.idf_heap_info(getattr(_esp, "HEAP_DATA", 0))
        except Exception:
            _info = []
        for _r in (_info or [])[:8]:
            try:
                _regions.append({"caps": int(_r[0]), "free": int(_r[1]),
                                 "largest": int(_r[2]), "min_free": int(_r[3])})
            except Exception:
                pass
        s["idf_heap"] = _regions
    except Exception:
        s["idf_heap"] = []
    # --- chip / firmware ---
    try:
        import machine as _mach
        try:
            s["cpu_freq"] = int(_mach.freq())
        except Exception:
            s["cpu_freq"] = 0
        try:
            s["unique_id"] = _hexbytes(_mach.unique_id())
        except Exception:
            s["unique_id"] = ""
    except Exception:
        s["cpu_freq"] = 0
        s["unique_id"] = ""
    try:
        import esp32 as _esp2
        try:
            s["flash_size"] = int(_esp2.flash_size())
        except Exception:
            s["flash_size"] = 0
        try:
            s["mcu_temp_c"] = float(_esp2.mcu_temperature())
        except Exception:
            s["mcu_temp_c"] = 0
    except Exception:
        s["flash_size"] = 0
        s["mcu_temp_c"] = 0
    try:
        import os as _os
        try:
            _u = _os.uname()
            s["board"] = str(_u[0])
            s["board_machine"] = str(_u[4])
            s["board_version"] = str(_u[3])[:120]
        except Exception:
            s["board"] = ""
            s["board_machine"] = ""
            s["board_version"] = ""
    except Exception:
        s["board"] = ""
        s["board_machine"] = ""
        s["board_version"] = ""
    try:
        import sys as _sys
        try:
            s["platform"] = str(_sys.platform)
        except Exception:
            s["platform"] = ""
        try:
            s["mpy_version"] = str(_sys.version)[:120]
        except Exception:
            s["mpy_version"] = ""
    except Exception:
        s["platform"] = ""
        s["mpy_version"] = ""
    # --- clock (best-effort: 2000-01-01 until NTP syncs after a cold boot) ---
    try:
        import time as _t2
        _lt = _t2.localtime()
        s["now"] = "%s-%s-%s %s:%s:%s" % (
            _lt[0], _p2(_lt[1]), _p2(_lt[2]), _p2(_lt[3]), _p2(_lt[4]), _p2(_lt[5]))
    except Exception:
        s["now"] = ""
    # --- storage (LittleFS) ---
    try:
        import os as _os2
        try:
            _v = _os2.statvfs(_FS_ROOT or "/")
            _fr = int(_v[1])
            _total = int(_v[2]) * _fr
            _freeb = int(_v[3]) * _fr
            s["fs_total"] = _total
            s["fs_free"] = _freeb
            s["fs_used"] = _total - _freeb
        except Exception:
            s["fs_total"] = 0
            s["fs_free"] = 0
            s["fs_used"] = 0
    except Exception:
        s["fs_total"] = 0
        s["fs_free"] = 0
        s["fs_used"] = 0
    # --- app files (sizes + counts; chat log read line-by-line, low RAM) ---
    try:
        import agent_tools as _at
        try:
            import os as _os3
            s["log_bytes"] = int(_os3.stat(_at.active_log_path())[6])
        except Exception:
            s["log_bytes"] = 0
        try:
            import os as _os4
            s["mem_bytes"] = int(_os4.stat(_at.MEM_PATH)[6])
        except Exception:
            s["mem_bytes"] = 0
        try:
            import os as _os5
            try:
                s["config_bytes"] = int(_os5.stat("config.yaml")[6])
            except Exception:
                s["config_bytes"] = int(_os5.stat("config.json")[6])
        except Exception:
            s["config_bytes"] = 0
        try:
            _turns = 0
            with open(_at.active_log_path(), "r") as _f:
                for _ln in _f:
                    if _ln.strip():
                        _turns += 1
            s["chat_lines"] = _turns
        except Exception:
            s["chat_lines"] = 0
        try:
            _mem = _at.readMemoryFacts()
            _n = 0
            for _ln in _mem.split("\n"):
                if _ln.strip():
                    _n += 1
            s["mem_facts"] = _n
        except Exception:
            s["mem_facts"] = 0
        try:
            s["fs_ok"] = bool(_at.gFsOk)
        except Exception:
            s["fs_ok"] = False
    except Exception:
        s["log_bytes"] = 0
        s["mem_bytes"] = 0
        s["config_bytes"] = 0
        s["chat_lines"] = 0
        s["mem_facts"] = 0
        s["fs_ok"] = False
    # --- network / service ---
    try:
        import net as _net
        import config as _cfg
        s["ap_mode"] = bool(_net.apMode)
        try:
            s["wifi_connected"] = bool(_net.is_connected())
        except Exception:
            s["wifi_connected"] = False
        try:
            s["ip"] = _net.local_ip()
        except Exception:
            s["ip"] = ""
        try:
            s["mdns"] = "http://" + getattr(_cfg, "cfgMdnsName", _cfg.MDNS_NAME) + ".local"
        except Exception:
            s["mdns"] = ""
        try:
            s["endpoint_configured"] = len(_cfg.cfgEndpoint or "") > 0
        except Exception:
            s["endpoint_configured"] = False
        try:
            s["endpoint"] = _cfg.cfgEndpoint
        except Exception:
            s["endpoint"] = ""
        try:
            s["model"] = _cfg.cfgModel
        except Exception:
            s["model"] = ""
        try:
            s["auth_required"] = (not _net.apMode) and len(_cfg.cfgAuthToken or "") > 0
        except Exception:
            s["auth_required"] = False
        try:
            s["tools_mask"] = int(_cfg.gToolsMask)
        except Exception:
            s["tools_mask"] = 0
    except Exception:
        s["ap_mode"] = False
        s["wifi_connected"] = False
        s["ip"] = ""
        s["mdns"] = ""
        s["endpoint_configured"] = False
        s["endpoint"] = ""
        s["model"] = ""
        s["auth_required"] = False
        s["tools_mask"] = 0
    try:
        import network as _nw
        try:
            _sta = _nw.WLAN(_nw.STA_IF)
            try:
                s["ssid"] = str(_sta.config("essid")) if _sta.isconnected() else ""
            except Exception:
                s["ssid"] = ""
            try:
                s["rssi"] = int(_sta.status("rssi"))
            except Exception:
                try:
                    s["rssi"] = int(_sta.status())
                except Exception:
                    s["rssi"] = 0
            try:
                s["mac"] = _macstr(_sta.config("mac"))
            except Exception:
                s["mac"] = ""
        except Exception:
            s["ssid"] = ""
            s["rssi"] = 0
            s["mac"] = ""
        try:
            _ap = _nw.WLAN(_nw.AP_IF)
            try:
                s["ap_active"] = bool(_ap.active())
            except Exception:
                s["ap_active"] = False
            try:
                s["ap_ip"] = str(_ap.ifconfig()[0]) if s["ap_active"] else ""
            except Exception:
                s["ap_ip"] = ""
        except Exception:
            s["ap_active"] = False
            s["ap_ip"] = ""
    except Exception:
        s["ssid"] = ""
        s["rssi"] = 0
        s["mac"] = ""
        s["ap_active"] = False
        s["ap_ip"] = ""
    # --- tools ---
    try:
        import agent_tools as _at2
        import config as _cfg2
        _names = []
        for _i in range(len(_at2.TOOL_REGISTRY)):
            try:
                if (_cfg2.gToolsMask >> _i) & 1:
                    _names.append(_at2.toolNameAt(_i))
            except Exception:
                pass
        s["tools_enabled"] = _names
        s["tools_total"] = len(_at2.TOOL_REGISTRY)
    except Exception:
        s["tools_enabled"] = []
        s["tools_total"] = 0
    # --- pins (capability lists only — reporting never drives a pin) ---
    try:
        import agent_tools as _at3
        try:
            _s3 = bool(_at3._is_s3())
        except Exception:
            _s3 = False
        s["chip_s3"] = _s3
        try:
            s["pins_writable"] = sorted(list(_at3._WRITE_S3 if _s3 else _at3._WRITE_CLASSIC))
        except Exception:
            s["pins_writable"] = []
        try:
            s["pins_adc"] = sorted(list(_at3._ADC_S3 if _s3 else _at3._ADC_CLASSIC))
        except Exception:
            s["pins_adc"] = []
    except Exception:
        s["chip_s3"] = False
        s["pins_writable"] = []
        s["pins_adc"] = []
    # --- optional I2C scan (read-only probe, ?i2c=1) ---
    if do_i2c:
        _i2c = {}
        try:
            import machine as _mi2c
            _I2C = getattr(_mi2c, "I2C", None)
            _Pin = getattr(_mi2c, "Pin", None)
            if _I2C is None or _Pin is None:
                _i2c = {"error": "no I2C support"}
            else:
                try:
                    import agent_tools as _at_i2c
                    _s3bus = bool(_at_i2c._is_s3())
                except Exception:
                    _s3bus = True
                # S3 boards use 8/9; classic ESP32 uses 21/22. Only probe the
                # bus that exists so the page doesn't show a bogus error.
                _buses = (("sda8_scl9", 8, 9),) if _s3bus else (("sda21_scl22", 21, 22),)
                for _bus in _buses:
                    _name = _bus[0]
                    try:
                        _bus_o = _I2C(0, sda=_Pin(_bus[1]), scl=_Pin(_bus[2]), freq=100000)
                        try:
                            _addrs = _bus_o.scan()
                        except Exception as _e:
                            _i2c[_name] = {"error": str(_e)[:60]}
                            continue
                        _out = []
                        for _a in _addrs:
                            _out.append("0x" + _hex2(_a))
                        _i2c[_name] = _out
                        try:
                            _bus_o.deinit()
                        except Exception:
                            pass
                    except Exception as _e:
                        _i2c[_name] = {"error": str(_e)[:60]}
        except Exception as _e:
            _i2c = {"error": str(_e)[:60]}
        s["i2c"] = _i2c
    else:
        s["i2c"] = None
    # --- D3 usage counters (RAM only, reset on boot — see _STATS_* above) ---
    try:
        s["turns_since_boot"] = int(_STATS_TURNS_SINCE_BOOT)
    except Exception:
        s["turns_since_boot"] = 0
    try:
        import agent_tools as _at_stats
        _tc = getattr(_at_stats, "_TOOL_CALL_COUNTS", None)
        s["tool_calls"] = dict(_tc) if isinstance(_tc, dict) else {}
    except Exception:
        s["tool_calls"] = {}
    try:
        s["last_chat_ms"] = int(_STATS_LAST_CHAT_MS)
    except Exception:
        s["last_chat_ms"] = 0
    try:
        s["last_upstream_ms"] = (int(_STATS_LAST_UPSTREAM_MS)
                                 if _STATS_LAST_UPSTREAM_MS is not None
                                 else None)
    except Exception:
        s["last_upstream_ms"] = None
    return s


# ---------- doctor (Phase 0 diagnostics: heap/wifi/ntp/dns/upstream/files) ----------
# MicroPython-safe: utf-8 only, no new third-party imports, small bounded
# allocations. All probes are best-effort and never raise — failures surface
# as ok:false fields, never a 500.
_DOCTOR_HEAP_OK = 1000000
# Same value as net._PLAUSIBLE_TIME (2024-01-01; MicroPython epoch is 2000).
_DOCTOR_PLAUSIBLE_TIME = 757382400
_DOCTOR_FILES = ("config.yaml", "config.json", "config.json.bak", "opt/data/memory.txt", "opt/data/user.txt",
                  "opt/data/cron.json",
                  "opt/data/sessions/active.json",
                 "opt/data/tg.json")
_DOCTOR_UPSTREAM_PORT = 443
_DOCTOR_UPSTREAM_TIMEOUT = 5


def _doctor_heap_free():
    try:
        import gc as _gc
        try:
            _gc.collect()
        except Exception:
            pass
        return int(_gc.mem_free())
    except Exception:
        return 0


def _doctor_verdict(heap_free):
    """Return (psram_ok, firmware_verdict) for a heap size in bytes."""
    if heap_free > _DOCTOR_HEAP_OK:
        return True, "SPIRAM_OCT"
    return False, "standard-build-suspect"


def _doctor_now_ms():
    try:
        import time as _t
        if hasattr(_t, "ticks_ms"):
            return int(_t.ticks_ms())
        return int(_t.time() * 1000)
    except Exception:
        return 0


def _doctor_since_ms(t0):
    try:
        import time as _t
        if hasattr(_t, "ticks_ms") and hasattr(_t, "ticks_diff"):
            return int(_t.ticks_diff(_t.ticks_ms(), t0))
        return int(_t.time() * 1000) - int(t0)
    except Exception:
        return 0


def _doctor_file_size(norm):
    """Size of a state file in bytes; -1 when missing (never raises)."""
    import os
    try:
        return int(os.stat(_fs_full(norm))[6])
    except Exception:
        return -1


def _doctor_check_dns(host):
    """Single getaddrinfo attempt (no timeout exists on device). Never raises."""
    t0 = _doctor_now_ms()
    if not host:
        return False, 0
    try:
        import socket
        infos = socket.getaddrinfo(host, 443)
        return (True if infos else False), _doctor_since_ms(t0)
    except Exception:
        try:
            return False, _doctor_since_ms(t0)
        except Exception:
            return False, 0


def _doctor_check_upstream(host, port=_DOCTOR_UPSTREAM_PORT,
                           timeout=_DOCTOR_UPSTREAM_TIMEOUT):
    """Plain TCP connect (no TLS), small buffers, then close. Never raises."""
    t0 = _doctor_now_ms()
    if not host:
        return False, 0
    try:
        import socket
    except ImportError:
        return False, 0
    s = None
    try:
        s = socket.socket()
        try:
            s.settimeout(timeout)
        except Exception:
            pass
        try:
            addrs = _resolve_all_ipv4(host, port)
        except Exception:
            addrs = []
        if addrs:
            s.connect(addrs[0])
        else:
            s.connect((host, port))
        return True, _doctor_since_ms(t0)
    except Exception:
        try:
            return False, _doctor_since_ms(t0)
        except Exception:
            return False, 0
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def _collect_doctor():
    """Build the GET /api/doctor payload. Never raises (fields degrade)."""
    heap_free = _doctor_heap_free()
    psram_ok, verdict = _doctor_verdict(heap_free)
    try:
        import time as _t
        ntp_ok = bool(_t.time() > _DOCTOR_PLAUSIBLE_TIME)
    except Exception:
        ntp_ok = False
    wifi_connected, ip, ap_mode = False, "", False
    try:
        import net as _net
        ap_mode = bool(_net.apMode)
        try:
            wifi_connected = bool(_net.is_connected())
        except Exception:
            wifi_connected = False
        try:
            ip = _net.local_ip() or ""
        except Exception:
            ip = ""
    except Exception:
        pass
    endpoint = ""
    try:
        import config as _cfg
        endpoint = _cfg.cfgEndpoint or ""
    except Exception:
        endpoint = ""
    host = ""
    if endpoint:
        try:
            _https, host, _port, _path = _split_url(endpoint)
        except Exception:
            host = ""
    dns_ok, dns_ms = _doctor_check_dns(host)
    upstream_ok, upstream_ms = _doctor_check_upstream(host)
    files = {}
    for name in _DOCTOR_FILES:
        try:
            files[name] = _doctor_file_size(name)
        except Exception:
            files[name] = -1
    return {"heap_free": heap_free, "psram_ok": psram_ok,
            "firmware_verdict": verdict,
            "wifi": {"connected": wifi_connected, "ip": ip,
                     "ap_mode": ap_mode},
            "ntp_ok": ntp_ok,
            "endpoint": endpoint, "host": host,
            "dns_ok": dns_ok, "dns_ms": dns_ms,
            "upstream_ok": upstream_ok, "upstream_ms": upstream_ms,
            "files": files}


# ---------- Phase 9: toolset map (static grouping for /functions) ----------
# Maps every registered tool name -> toolset. The 22 TOOL dicts are NEVER
# touched (append-only registry, bitmask order frozen); this table lives in
# server.py only and the /functions page groups by the "toolset" field of
# GET /api/tools. Unknown names fall back to "agent".
TOOLSET_MAP = {
    "get_status": "device", "gpio_write": "device", "gpio_read": "device",
    "adc_read": "device", "wifi_scan": "device", "restart_device": "device",
    "blink": "device",
    "mem_save": "memory", "mem_read": "memory", "memory": "memory",
    "skills": "skills", "skill_view": "skills",
    "session_search": "sessions",
    "read_file": "files", "write_file": "files",
    "patch_file": "files", "search_files": "files",
    "web_fetch": "web",
    "cron": "agent", "todo": "agent", "delegate_task": "agent",
    "exec_py": "agent",
}
TOOLSET_ORDER = ("device", "memory", "skills", "sessions", "files",
                 "web", "agent")


def tool_toolset(name):
    """Toolset for a tool name (Phase 9 grouping). Never raises."""
    try:
        return TOOLSET_MAP.get(str(name), "agent")
    except Exception:
        return "agent"


def _system_prompt():
    """Phase 9 prompt alignment seam: tiered Mini prompt, legacy fallback.

    Used by the SSE stream path and GET /api/tools prompt_preview (both were
    legacy buildSystemPrompt until Phase 9). One call per request keeps the
    frozen-per-turn rule. Host tests monkeypatch prompt.buildMiniPrompt to
    verify the seam.
    """
    try:
        import prompt as _pm
        return _pm.buildMiniPrompt()
    except Exception:
        import agent_tools as _at
        return _at.buildSystemPrompt()


def _parse_approval_bool(v, default=None):
    """Loose bool parse for approval toggles. None stays None (preserve)."""
    if v is None:
        return default
    if v is True or v == 1:
        return True
    if v is False or v == 0:
        return False
    try:
        s = str(v).strip().lower()
    except Exception:
        return default
    if s in ("1", "true", "on", "yes", "checked"):
        return True
    if s in ("0", "false", "off", "no"):
        return False
    return default


def _agent_get_approvals():
    """(memory_write_approval, skills_write_approval) from live modules."""
    mem_on = False
    sk_on = True
    try:
        import memory as _mm
        mem_on = bool(_mm.approval_enabled())
    except Exception:
        pass
    try:
        import skillstore as _sk
        sk_on = bool(_sk.approval_enabled())
    except Exception:
        pass
    return mem_on, sk_on


def _agent_set_approvals(mem_val, sk_val):
    """Persist approval toggles into config.yaml. None = preserve."""
    if mem_val is None and sk_val is None:
        return
    try:
        import config as _cfg
        _cfg.saveApprovals(mem_val, sk_val)
    except Exception:
        pass


# ---------- /api/agent payload helpers (Phase 1: fallback + max_iters) ----------
# Module-level (microdot-free) so host tests can drive them directly.
# Unknown POST keys are ignored; GET never leaks full keys (masked only).


def _agent_get_payload():
    """GET /api/agent body. Never includes full API keys."""
    import config
    try:
        iters = int(config.agent_max_iters)
    except Exception:
        iters = 3
    if iters < 1:
        iters = 1
    if iters > 5:
        iters = 5
    try:
        mem_on, sk_on = _agent_get_approvals()
    except Exception:
        mem_on, sk_on = False, True
    return {"endpoint": config.cfgEndpoint, "model": config.cfgModel,
            "api_key_masked": config.maskedKey(config.cfgApiKey),
            "fallback_endpoint": getattr(config, "cfgFallbackEndpoint", ""),
            "fallback_model": getattr(config, "cfgFallbackModel", ""),
            "fallback_key_masked": config.maskedKey(getattr(config, "cfgFallbackKey", "")),
            "agent_max_iters": iters,
            "memory_write_approval": bool(mem_on),
            "skills_write_approval": bool(sk_on)}


def _agent_apply_post(d):
    """Apply a POST /api/agent body. Returns (err_text_or_None, result_dict).

    Unknown keys are ignored. Absent fallback/max_iters keys preserve current
    values; present-but-empty fallback keys clear them. Primary key/model
    keep the legacy rule: empty preserves the stored value.
    """
    import config
    ep = str(d.get("endpoint", "") or "").strip() or config.cfgEndpoint
    if "apiKey" in d:
        _raw_key = d.get("apiKey")
    elif "api_key" in d:
        _raw_key = d.get("api_key")
    else:
        _raw_key = None
    if _raw_key is None:
        key = config.cfgApiKey
    else:
        key = str(_raw_key or "").strip() or config.cfgApiKey
    model = str(d.get("model", "") or "").strip() or config.cfgModel or "gpt-4o-mini"
    if not ep:
        return "endpoint required", None
    if "fallback_endpoint" in d:
        fb_ep = str(d.get("fallback_endpoint") or "").strip()
    elif "fallbackEndpoint" in d:
        fb_ep = str(d.get("fallbackEndpoint") or "").strip()
    else:
        fb_ep = None
    if "fallback_key" in d:
        fb_key = str(d.get("fallback_key") or "").strip()
    elif "fallbackKey" in d:
        fb_key = str(d.get("fallbackKey") or "").strip()
    else:
        fb_key = None
    if "fallback_model" in d:
        fb_model = str(d.get("fallback_model") or "").strip()
    elif "fallbackModel" in d:
        fb_model = str(d.get("fallbackModel") or "").strip()
    else:
        fb_model = None
    iters = None
    for _k in ("agent_max_iters", "max_iters", "maxIters"):
        if _k in d:
            try:
                n = int(d.get(_k))
                if n < 1:
                    n = 1
                if n > 5:
                    n = 5
                iters = n
            except Exception:
                iters = None
            break
    config.saveAgentOnly(ep, key, model, fb_ep, fb_key, fb_model, iters)
    # Phase 9: memory/skills write_approval toggles (absent = preserve).
    try:
        mem_val = None
        for _k in ("memory_write_approval", "memory.write_approval",
                   "mem_write_approval", "memory_approval"):
            if _k in d:
                mem_val = _parse_approval_bool(d.get(_k), None)
                break
        try:
            _msec = d.get("memory")
            if isinstance(_msec, dict) and "write_approval" in _msec:
                mem_val = _parse_approval_bool(_msec.get("write_approval"), mem_val)
        except Exception:
            pass
        sk_val = None
        for _k in ("skills_write_approval", "skills.write_approval",
                   "skill_write_approval", "skills_approval"):
            if _k in d:
                sk_val = _parse_approval_bool(d.get(_k), None)
                break
        try:
            _ssec = d.get("skills")
            if isinstance(_ssec, dict) and "write_approval" in _ssec:
                sk_val = _parse_approval_bool(_ssec.get("write_approval"), sk_val)
        except Exception:
            pass
        _agent_set_approvals(mem_val, sk_val)
    except Exception:
        pass
    return None, {"ok": True, "rebooting": False}


# ---------- backup (D5: one-JSON state export, secrets ALWAYS redacted) ----------
# GET /api/backup body. The bot token (tg.json), wifi password, API keys and
# the device auth token are NEVER included raw: config values reuse the
# maskedKey shapes from /api/agent (or presence bools), and the gateway
# section reuses gateway.status() which is presence-only by design.
_BACKUP_CHATLOG_TAIL = 20


def _collect_backup():
    """Build the GET /api/backup payload. Never raises (fields degrade).

    Shape: {ok, memory, user, chatlog_tail, chatlog_bytes, cron,
    skills[{name,desc,content}], bundles, pending_counts, config (redacted),
    gateway (presence-only), note}. No restore in v1: restore = /files
    editor + reboot (documented on /system)."""
    out = {"ok": True}
    try:
        import agent_tools as _at
        try:
            out["memory"] = _at.readMemoryFacts()[:3000]
        except Exception:
            out["memory"] = ""
        try:
            import memory as _mm
            out["user"] = _mm.read_text("user")[:2000]
        except Exception:
            out["user"] = ""
        try:
            tail, nbytes = _read_log_tail(_at.active_log_path(),
                                          _BACKUP_CHATLOG_TAIL)
            out["chatlog_tail"] = tail
            out["chatlog_bytes"] = nbytes
        except Exception:
            out["chatlog_tail"] = []
            out["chatlog_bytes"] = 0
    except Exception:
        out["memory"] = ""
        out["user"] = ""
        out["chatlog_tail"] = []
        out["chatlog_bytes"] = 0
    try:
        import cron as _cron
        out["cron"] = _cron.list_jobs()
    except Exception:
        out["cron"] = {"success": False, "jobs": [], "count": 0}
    try:
        import skillstore as _sk
        skills = []
        try:
            idx = _sk.index()
        except Exception:
            idx = []
        for _e in idx:
            try:
                _n = _e.get("name", "") if isinstance(_e, dict) else ""
                _v = _sk.view(_n)
                if isinstance(_v, dict) and _v.get("success"):
                    skills.append({"name": _v.get("name", _n),
                                   "desc": _v.get("desc", ""),
                                   "content": _v.get("content", "")})
                else:
                    skills.append({"name": _n,
                                   "desc": _e.get("desc", "") if isinstance(_e, dict) else "",
                                   "content": ""})
            except Exception:
                pass
        out["skills"] = skills
        try:
            out["bundles"] = _sk.list_bundles()
        except Exception:
            out["bundles"] = []
        try:
            _sp = len(_sk.list_pending())
        except Exception:
            _sp = 0
    except Exception:
        out["skills"] = []
        out["bundles"] = []
        _sp = 0
    try:
        import memory as _mm2
        try:
            _mp = len(_mm2.list_pending())
        except Exception:
            _mp = 0
    except Exception:
        _mp = 0
    out["pending_counts"] = {"memory": _mp, "skills": _sp}
    try:
        import config as _cfg
        out["config"] = {
            "wifi_ssid": _cfg.cfgSsid,
            "api_endpoint": _cfg.cfgEndpoint,
            "api_model": _cfg.cfgModel,
            "api_key_masked": _cfg.maskedKey(_cfg.cfgApiKey),
            "fallback_endpoint": getattr(_cfg, "cfgFallbackEndpoint", ""),
            "fallback_model": getattr(_cfg, "cfgFallbackModel", ""),
            "fallback_key_masked": _cfg.maskedKey(getattr(_cfg, "cfgFallbackKey", "")),
            "auth_configured": len(_cfg.cfgAuthToken or "") > 0,
            "tools_mask": int(getattr(_cfg, "gToolsMask", 0)),
            "agent_max_iters": int(getattr(_cfg, "agent_max_iters", 3)),
        }
    except Exception:
        out["config"] = {}
    try:
        import gateway as _gw
        out["gateway"] = _gw.status()
    except Exception:
        out["gateway"] = {"success": False, "configured": False,
                          "allow": [], "requests": [], "offset": 0}
    out["note"] = ("Secrets redacted: api_key/wifi_pass/auth_token/bot_token "
                   "are never in this payload (masked shapes or presence "
                   "flags only). No restore in v1 — restore data files via "
                   "/api/files and system files via /api/system/files, then reboot.")
    return out


# Microdot imports are lazy so host-side unit tests can import helpers
# without the framework installed.
_app = None


def get_app():
    global _app
    if _app is not None:
        return _app
    from microdot import Microdot, Response
    try:
        from microdot import send_file
    except ImportError:
        send_file = Response.send_file
    import config
    import net

    app = Microdot()

    # ---------- auth helpers ----------
    def auth_enabled():
        if net.apMode:
            return False
        return len(config.cfgAuthToken or "") > 0

    def _hdr(request, name):
        try:
            h = request.headers.get(name, "")
            if isinstance(h, bytes):
                h = h.decode()
            return h or ""
        except Exception:
            return ""

    def is_authenticated(request):
        if not auth_enabled():
            return True
        h = _hdr(request, "Authorization")
        if h.startswith("Bearer "):
            v = h[7:].strip()
            if v and v == config.cfgAuthToken:
                return True
        x = _hdr(request, "X-Auth-Token").strip()
        if x and x == config.cfgAuthToken:
            return True
        return False

    def need_auth(request):
        if is_authenticated(request):
            return None
        return {"error": "auth required"}, 401

    def _body_json(request):
        try:
            j = request.json
            if isinstance(j, dict):
                return j
        except Exception:
            pass
        # fallback: raw body
        try:
            raw = request.body
            if isinstance(raw, bytes):
                raw = raw.decode()
            if raw:
                j = json.loads(raw)
                if isinstance(j, dict):
                    return j
        except Exception:
            pass
        return None

    # ---------- pages ----------
    #
    # The dashboard is a compiled React SPA (see ui/). Firmware ships exactly
    # three web files:
    #     www/index.html      the shell
    #     www/assets/app.js   the whole app, one chunk
    #     www/assets/app.css  the whole design system
    # Everything else is an API call, so page routes are handled by serving
    # index.html and letting the client router take over.

    _WWW = "www/"
    _MIME = {
        "html": "text/html; charset=utf-8",
        "js": "application/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "svg": "image/svg+xml",
        "json": "application/json",
        "ico": "image/x-icon",
        "txt": "text/plain; charset=utf-8",
        "png": "image/png",
        "webp": "image/webp",
        "woff2": "font/woff2",
        "md": "text/markdown; charset=utf-8",
    }
    # Files the UI may serve out of www/. Anything else 404s instead of
    # exposing arbitrary device files through the web root.
    _WWW_OK = ("index.html", "favicon.svg")
    _WWW_DIRS_OK = ("assets/",)

    def _www_safe(relpath):
        """Normalise a request path to a safe www-relative path, or None."""
        p = (relpath or "").strip()
        while p.startswith("/"):
            p = p[1:]
        if not p or ".." in p or "\\" in p or p.startswith("."):
            return None
        if p in _WWW_OK:
            return p
        for d in _WWW_DIRS_OK:
            if p.startswith(d):
                name = p[len(d):]
                if not name or "/" in name or name.startswith("."):
                    return None
                return p
        return None

    def _mime_for(name):
        idx = name.rfind(".")
        ext = name[idx + 1:].lower() if idx >= 0 else ""
        return _MIME.get(ext, "application/octet-stream")

    def _serve_www(relpath, cache=None, gz=False):
        """Read a file from www/ and return it with explicit headers.

        `gz=True` prefers `<path>.gz` when the client accepts gzip. MicroPython
        cannot compress at request time, so the gzipped twin is prebuilt on the
        host — it is the difference between a ~7 s and a ~2 s first load.
        """
        safe = _www_safe(relpath)
        if safe is None:
            return None
        base = _WWW + safe
        content_encoding = None
        full = base
        if gz:
            try:
                with open(base + ".gz", "rb") as f:
                    data = f.read()
                full = base + ".gz"
                content_encoding = "gzip"
            except Exception:
                data = None
        if not gz or content_encoding is None:
            try:
                with open(base, "rb") as f:
                    data = f.read()
            except Exception:
                return None
        if cache is None:
            cache = "public, max-age=31536000, immutable" \
                if safe.startswith("assets/") else "no-cache"
        headers = {"Content-Type": _mime_for(safe),
                   "Cache-Control": cache}
        if content_encoding:
            headers["Content-Encoding"] = content_encoding
            headers["Vary"] = "Accept-Encoding"
        return data, 200, headers

    @app.get("/")
    async def _index(request):
        if net.apMode and not config.cfgSsid:
            return Response.redirect("/wifi")
        res = _serve_www("index.html", cache="no-cache")
        if res is None:
            return "UI bundle missing. Deploy www/index.html and www/assets/.",
        return res

    def _accepts_gzip(request):
        try:
            enc = request.headers.get("Accept-Encoding", "") or ""
        except Exception:
            return False
        if isinstance(enc, bytes):
            try:
                enc = enc.decode()
            except Exception:
                return False
        return "gzip" in enc.lower()

    @app.get("/assets/<name>")
    async def _asset(request, name):
        res = _serve_www("assets/" + name, gz=_accepts_gzip(request))
        if res is None:
            return {"error": "not found"}, 404
        return res

    @app.get("/favicon.svg")
    async def _favicon(request):
        res = _serve_www("favicon.svg")
        if res is None:
            return {"error": "not found"}, 404
        return res

    # SPA fallback is registered at the very end of get_app(), after every
    # /api route — a catch-all declared earlier would swallow them.

    # ---------- status ----------
    @app.get("/api/status")
    async def _status(request):
        import agent_tools
        if auth_enabled() and not is_authenticated(request):
            return {"ap_mode": net.apMode,
                    "wifi_connected": net.is_connected(),
                    "auth_required": True,
                    "endpoint_configured": len(config.cfgEndpoint or "") > 0}, 401
        try:
            import network
            sta = network.WLAN(network.STA_IF)
            ssid = ""
            try:
                ssid = sta.config("essid") if sta.isconnected() else ""
            except Exception:
                ssid = ""
            ip = net.local_ip()
        except Exception:
            ssid, ip = "", net.local_ip()
        try:
            import gc
            heap = gc.mem_free()
        except Exception:
            heap = 0
        try:
            import time
            up = int(time.ticks_ms() // 1000) if hasattr(time, "ticks_ms") else 0
        except Exception:
            up = 0
        log_bytes, mem_bytes = 0, 0
        if agent_tools.gFsOk:
            try:
                import os
                log_bytes = os.stat(agent_tools.active_log_path())[6]
            except Exception:
                pass
            try:
                import os
                mem_bytes = os.stat(agent_tools.MEM_PATH)[6]
            except Exception:
                pass
        return {"auth_required": auth_enabled(),
                "ap_mode": net.apMode,
                "wifi_connected": net.is_connected(),
                "ssid": ssid,
                "ip": ip,
                "mdns": "http://" + config.MDNS_NAME + ".local",
                "endpoint_configured": len(config.cfgEndpoint or "") > 0,
                "endpoint": config.cfgEndpoint,
                "model": config.cfgModel,
                "free_heap": heap,
                "uptime_s": up,
                "fs_ok": agent_tools.gFsOk,
                "tools_mask": config.gToolsMask,
                "log_bytes": log_bytes,
                "mem_bytes": mem_bytes}

    @app.get("/api/stats")
    async def _api_stats(request):
        na = need_auth(request)
        if na:
            return na
        do_i2c = False
        try:
            v = request.args.get("i2c", "") if hasattr(request, "args") else ""
            do_i2c = str(v) in ("1", "true", "yes")
        except Exception:
            do_i2c = False
        return _collect_stats(do_i2c)

    @app.get("/api/doctor")
    async def _api_doctor(request):
        na = need_auth(request)
        if na:
            return na
        return _collect_doctor()

    @app.get("/api/auth")
    async def _get_auth(request):
        return {"auth_required": auth_enabled(), "ap_mode": net.apMode,
                "username": LOGIN_USERNAME}

    @app.post("/api/login")
    async def _login(request):
        # Stateless Hermes-style verifier: username must be admin (fixed),
        # password is the device auth token. Not auth-gated (it IS the gate).
        # Accepts common key variants so hand-rolled clients don't 400.
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        u = d.get("username", d.get("user", d.get("name", "")))
        p = d.get("password", d.get("pass", d.get("token", d.get("passwd", ""))))
        if not str(u or "").strip() or not str(p or ""):
            return {"error": "username and password required"}, 400
        if _verify_login(u, p):
            return {"ok": True}
        return {"error": "invalid username or password"}, 401

    @app.post("/api/auth")
    async def _save_auth(request):
        if auth_enabled() and not is_authenticated(request):
            return {"error": "auth required"}, 401
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        nt = str(d.get("token", "") or "").strip()
        if nt and len(nt) < 8:
            return {"error": "token too short (min 8 chars)"}, 400
        if len(nt) > 128:
            nt = nt[:128]
        config.saveAuthToken(nt)
        print("[auth] token %s" % ("set" if nt else "cleared"))
        return {"ok": True, "auth_required": auth_enabled()}

    # ---------- wifi ----------
    @app.get("/api/scan")
    async def _scan(request):
        na = need_auth(request)
        if na:
            return na
        import time
        now = time.ticks_ms() if hasattr(time, "ticks_ms") else 0

        def _age_ok():
            try:
                import time as _t
                return _t.ticks_diff(now, _ap_scan_cache["at"]) < 30000
            except Exception:
                return False
        if _ap_scan_cache["body"] and _age_ok():
            return json.loads(_ap_scan_cache["body"])
        # blocking scan (~2s); cache result
        nets = []
        try:
            import network
            sta = network.WLAN(network.STA_IF)
            if not sta.active():
                try:
                    sta.active(True)
                except Exception:
                    pass
            raw = sta.scan()
            for n in raw[:30]:
                try:
                    ssid = n[0].decode() if isinstance(n[0], bytes) else str(n[0])
                except Exception:
                    ssid = ""
                try:
                    rssi = int(n[3])
                except Exception:
                    rssi = 0
                try:
                    secure = int(n[4]) != 0
                except Exception:
                    secure = False
                if ssid:
                    nets.append({"ssid": ssid, "rssi": rssi, "secure": secure})
        except Exception as e:
            return {"error": "scan failed: %s" % str(e)[:100]}, 500
        body = {"networks": nets, "count": len(nets)}
        _ap_scan_cache["body"] = json.dumps(body)
        try:
            _ap_scan_cache["at"] = now
        except Exception:
            pass
        return body

    @app.get("/api/wifi")
    async def _get_wifi(request):
        na = need_auth(request)
        if na:
            return na
        return {"wifi_ssid": config.cfgSsid}

    @app.post("/api/wifi")
    async def _save_wifi(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        ssid = str(d.get("ssid", "") or "").strip() or config.cfgSsid
        passwd = str(d.get("password", "") or "")
        if not ssid:
            return {"error": "SSID required"}, 400
        if not passwd and ssid == config.cfgSsid:
            passwd = config.cfgPass
        config.saveWifiOnly(ssid, passwd)
        print("Saved WiFi: ssid=%s (pass %d chars)" % (ssid, len(passwd)))

        async def _reboot():
            await asyncio.sleep(0.8)
            try:
                import machine
                machine.reset()
            except Exception:
                pass
        try:
            asyncio.create_task(_reboot())
        except Exception:
            pass
        return {"ok": True, "rebooting": True, "ssid": ssid}

    # ---------- agent ----------
    @app.get("/api/agent")
    async def _get_agent(request):
        na = need_auth(request)
        if na:
            return na
        return _agent_get_payload()

    @app.post("/api/agent")
    async def _save_agent(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        err, res = _agent_apply_post(d)
        if err:
            return {"error": err}, 400
        print("Saved agent: endpoint=%s model=%s (no reboot)" % (config.cfgEndpoint, config.cfgModel))
        return res

    @app.get("/api/models")
    async def _get_models(request):
        na = need_auth(request)
        if na:
            return na
        import time
        now = time.ticks_ms() if hasattr(time, "ticks_ms") else 0
        try:
            fresh = _models_cache["body"] and _models_cache["ep"] == config.cfgEndpoint and \
                time.ticks_diff(now, _models_cache["at"]) < 300000
        except Exception:
            fresh = bool(_models_cache["body"])
        if fresh:
            return json.loads(_models_cache["body"])
        if not config.cfgEndpoint:
            return {"error": "agent endpoint not configured. Open /agent."}, 400
        if not net.is_connected():
            return {"error": "ESP32 has no WiFi. Open /wifi."}, 503
        url = config.modelsUrl(config.cfgEndpoint)
        ok, res, code = _fetch_models_stream(url, config.cfgApiKey)
        if not ok:
            return {"error": res}, (code if code else 502)
        ids = [{"id": i} for i in res]
        body = {"models": ids, "count": len(ids)}
        _models_cache["body"] = json.dumps(body)
        _models_cache["ep"] = config.cfgEndpoint
        try:
            _models_cache["at"] = now
        except Exception:
            pass
        return body

    @app.get("/api/config")
    async def _get_config(request):
        na = need_auth(request)
        if na:
            return na
        return {"wifi_ssid": config.cfgSsid, "endpoint": config.cfgEndpoint,
                "model": config.cfgModel, "api_key_masked": config.maskedKey(config.cfgApiKey),
                "chat_entry_chars": int(getattr(config, "cfgChatEntryChars",
                                                config.DEFAULT_CHAT_ENTRY_CHARS)),
                "chat_entry_chars_min": int(config.CHAT_ENTRY_CHARS_MIN),
                "chat_entry_chars_max": int(config.CHAT_ENTRY_CHARS_MAX),
                "chat_log_max_kb": int(getattr(config, "cfgChatLogMaxKB",
                                               config.DEFAULT_CHAT_LOG_MAX_KB)),
                "chat_log_max_kb_min": int(config.CHAT_LOG_MAX_KB_MIN),
                "chat_log_max_kb_max": int(config.CHAT_LOG_MAX_KB_MAX),
                "chat_log_keep_kb": int(getattr(config, "cfgChatLogKeepKB",
                                                config.DEFAULT_CHAT_LOG_KEEP_KB)),
                "chat_log_keep_kb_min": int(config.CHAT_LOG_KEEP_KB_MIN),
                "chat_restore_turns": int(getattr(config, "cfgChatRestoreTurns",
                                                  config.DEFAULT_CHAT_RESTORE_TURNS)),
                "chat_restore_turns_min": int(config.CHAT_RESTORE_TURNS_MIN),
                "chat_restore_turns_max": int(config.CHAT_RESTORE_TURNS_MAX)}

    @app.post("/api/config")
    async def _save_config(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        # Chat-log retention (Config -> Chat history). Saved independently of
        # the provider/WiFi flow, and never reboots the device.
        chat_chars = None
        for _k in ("chat_entry_chars", "chatlog_entry_chars", "chat_history_chars"):
            if _k in d:
                chat_chars = config.saveChatEntryChars(d.get(_k))
                break
        storage = None
        if ("chat_log_max_kb" in d or "chat_log_keep_kb" in d
                or "chat_restore_turns" in d):
            def _pick(*names):
                for _n in names:
                    if _n in d:
                        return d.get(_n)
                return None
            storage = config.saveChatStorage(
                _pick("chat_log_max_kb", "chatlog_max_kb"),
                _pick("chat_log_keep_kb", "chatlog_keep_kb"),
                _pick("chat_restore_turns", "restore_turns", "chat_turns"))
        hasWifi = "ssid" in d or "password" in d
        hasAgent = "endpoint" in d or "apiKey" in d or "api_key" in d or "model" in d
        if not hasWifi and not hasAgent:
            if chat_chars is None and storage is None:
                return {"error": "nothing to save"}, 400
            out = {"ok": True, "rebooting": False}
            if chat_chars is not None:
                out["chat_entry_chars"] = chat_chars
            if storage is not None:
                out.update(storage)
            return out
        if hasWifi and not hasAgent:
            # delegate to wifi handler logic
            ssid = str(d.get("ssid", "") or "").strip() or config.cfgSsid
            passwd = str(d.get("password", "") or "")
            if not ssid:
                return {"error": "SSID required"}, 400
            if not passwd and ssid == config.cfgSsid:
                passwd = config.cfgPass
            config.saveWifiOnly(ssid, passwd)

            async def _rb():
                await asyncio.sleep(0.8)
                try:
                    import machine
                    machine.reset()
                except Exception:
                    pass
            try:
                asyncio.create_task(_rb())
            except Exception:
                pass
            return {"ok": True, "rebooting": True, "ssid": ssid}
        if hasAgent and not hasWifi:
            ep = str(d.get("endpoint", "") or "").strip() or config.cfgEndpoint
            key = str(d.get("apiKey", d.get("api_key", "")) or "").strip() or config.cfgApiKey
            model = str(d.get("model", "") or "").strip() or config.cfgModel
            if not ep:
                return {"error": "endpoint required"}, 400
            config.saveAgentOnly(ep, key, model)
            return {"ok": True, "rebooting": False}
        ssid = str(d.get("ssid", "") or "").strip() or config.cfgSsid
        passwd = str(d.get("password", "") or "")
        if not passwd and ssid == config.cfgSsid:
            passwd = config.cfgPass
        ep = str(d.get("endpoint", "") or "").strip() or config.cfgEndpoint
        key = str(d.get("apiKey", d.get("api_key", "")) or "").strip() or config.cfgApiKey
        model = str(d.get("model", "") or "").strip() or config.cfgModel
        if not ssid and not ep:
            return {"error": "SSID or endpoint required"}, 400
        if not ssid:
            ssid, passwd = config.cfgSsid, config.cfgPass
        config.saveConfig(ssid, passwd, ep, key, model)

        async def _rb2():
            await asyncio.sleep(0.8)
            try:
                import machine
                machine.reset()
            except Exception:
                pass
        try:
            asyncio.create_task(_rb2())
        except Exception:
            pass
        return {"ok": True, "rebooting": True}

    # ---------- schema-driven Config page ----------
    # The JSON form API returns fields + current values (secrets masked). The
    # YAML API is the raw editor: GET redacts by default, ?secrets=1 reveals,
    # POST validates and rewrites config.yaml. Both keep the older flat
    # /api/config and /api/agent endpoints working for Setup/Models/Keys.
    @app.get("/api/config/form")
    async def _get_config_form(request):
        na = need_auth(request)
        if na:
            return na
        try:
            return config.form_payload()
        except Exception as e:
            return {"error": "config form failed: %s" % str(e)[:120]}, 500

    @app.post("/api/config/form")
    async def _save_config_form(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        values = d.get("values")
        if not isinstance(values, dict):
            return {"error": "values object required"}, 400
        old_auth = config.cfgAuthToken
        try:
            out = config.save_form(values)
        except ValueError as e:
            return {"error": str(e)[:200]}, 400
        except Exception as e:
            return {"error": "save failed: %s" % str(e)[:120]}, 500
        res = {"ok": True, "path": config.CONFIG_PATH,
               "restart_required": bool(out.get("restart"))}
        if config.cfgAuthToken != old_auth:
            res["auth_token"] = config.cfgAuthToken
            res["auth_changed"] = True
        print("Saved config section via form (%d fields)" % len(values))
        return res

    @app.get("/api/config/yaml")
    async def _get_config_yaml(request):
        na = need_auth(request)
        if na:
            return na
        want = ""
        try:
            want = str(request.args.get("secrets", "") or "").lower()
        except Exception:
            pass
        reveal = want in ("1", "true", "yes", "on")
        try:
            text, redacted = config.yaml_text(redact=not reveal)
        except Exception as e:
            return {"error": "read failed: %s" % str(e)[:120]}, 500
        return {"yaml": text, "path": config.CONFIG_PATH,
                "redacted": bool(redacted), "version": config.CONFIG_VERSION}

    @app.post("/api/config/yaml")
    async def _save_config_yaml(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        text = d.get("yaml")
        if not isinstance(text, str):
            return {"error": "yaml text required"}, 400
        if len(text) > 100000:
            return {"error": "YAML too large (max 100KB)"}, 400
        old_auth = config.cfgAuthToken
        try:
            out = config.save_raw_yaml(text)
        except ValueError as e:
            return {"error": "invalid YAML: %s" % str(e)[:240]}, 400
        except Exception as e:
            return {"error": "save failed: %s" % str(e)[:120]}, 500
        res = {"ok": True, "path": config.CONFIG_PATH,
               "masked_secrets_preserved": bool(out.get("masked")),
               "restart_required": bool(out.get("restart")),
               "raw_preserved": bool(out.get("raw_preserved"))}
        if config.cfgAuthToken != old_auth:
            res["auth_token"] = config.cfgAuthToken
            res["auth_changed"] = True
        print("Saved config.yaml (%d bytes)" % len(text))
        return res

    # ---------- debug ----------
    @app.get("/api/debug-raw")
    async def _debug_raw(request):
        na = need_auth(request)
        if na:
            return na
        import llm as _llm
        msg = request.args.get("message", "Reply with just OK")
        if len(msg) > 500:
            msg = msg[:500]
        url = config.chatCompletionsUrl(config.cfgEndpoint)
        req = {"model": config.cfgModel, "temperature": 0.7, "max_tokens": 800,
               "stream": False,
               "messages": [{"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": msg}]}
        body = json.dumps(req)
        ok, resp, code = _llm.postLLM(body)
        if not ok:
            return {"url": url, "model": config.cfgModel, "http_code": 0,
                    "len": 0, "raw": resp[:2500], "parse": "request-failed"}
        out = {"url": url, "model": config.cfgModel, "http_code": code,
               "len": len(resp), "raw": resp[:2500]}
        try:
            res = json.loads(resp)
            out["parse"] = "ok"
            try:
                out["choices"] = len(res.get("choices", []))
            except Exception:
                out["choices"] = -1
            try:
                m = res["choices"][0]["message"]
                out["msg_keys"] = ",".join(list(m.keys()))
                c = m.get("content", "") or ""
                out["content_len"] = len(c)
                out["content_preview"] = c[:300]
                r1 = m.get("reasoning_content", "") or ""
                r2 = m.get("reasoning", "") or ""
                out["reasoning_content_len"] = len(r1)
                out["reasoning_len"] = len(r2)
                out["reasoning_preview"] = (r2 or r1)[:300]
                out["raw2"] = resp[2500:5000]
            except Exception as e:
                out["parse"] = "shape-error: %s" % str(e)[:100]
        except Exception:
            out["parse"] = "json-error"
        return out

    # ---------- chat ----------
    @app.post("/api/chat")
    async def _chat(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        msg = str(d.get("message", "") or "").strip()
        if not msg:
            return {"error": "message required"}, 400
        if len(msg) > 2000:
            msg = msg[:2000]
        if not net.is_connected():
            return {"error": "ESP32 has no WiFi. Open /wifi."}, 503
        hist = d.get("history", [])
        if not isinstance(hist, list):
            hist = []
        import llm as _llm
        import agent_tools
        # Which conversation this turn belongs to. The body carries the id
        # (explicit beats a shared pointer: two tabs never fight over one).
        _sid, _log_path = _resolve_session(d.get("session"), activate=True)
        # Phase 8 busy-guard: one upstream turn at a time (shared with the
        # Telegram poller — concurrent TLS turns risk a heap wedge). The
        # web key is mini:web:default; a second surface gets 429.
        try:
            import gateway as _gw_busy
            _busy_ok, _ = _gw_busy.acquire("mini:web:default")
        except Exception:
            _gw_busy = None
            _busy_ok = True
        if not _busy_ok:
            return {"error": "busy with another turn, try again shortly"}, 429
        out = {}
        # run blocking LLM loop in thread to keep server responsive (C++ blocks too)
        try:
            try:
                _t0 = _doctor_now_ms()
                try:
                    reply = _llm.callLLMWithTools(msg, hist, out,
                                                   log_path=_log_path)
                finally:
                    # D3 counters: guarded, never breaks the turn.
                    _stats_note_turn(_doctor_since_ms(_t0), _doctor_since_ms(_t0))
            except Exception as e:
                reply = "ERROR: %s" % str(e)[:200]
        finally:
            try:
                if _gw_busy is not None:
                    _gw_busy.release("mini:web:default")
            except Exception:
                pass
        print("[chat] q=%d chars -> a=%d chars tools=[%s]" % (len(msg), len(reply), out.get("tools_used", "")))
        if reply.startswith("ERROR:"):
            code = 500
            if "HTTP 4" in reply:
                code = 502
            if "not configured" in reply:
                code = 400
            return {"error": reply}, code
        resp = {"reply": reply, "model": config.cfgModel, "session": _sid}
        if out.get("reasoning"):
            resp["reasoning"] = out["reasoning"][:3000]
        if out.get("tools_used"):
            resp["tools_used"] = out["tools_used"]
        # delayed reboot after response is flushed
        if agent_tools.gRestartPending:
            async def _rb():
                await asyncio.sleep(0.6)
                try:
                    import machine
                    machine.reset()
                except Exception:
                    pass
            try:
                asyncio.create_task(_rb())
            except Exception:
                pass
        return resp

    @app.post("/api/chat-stream")
    async def _chat_stream(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        msg = str(d.get("message", "") or "").strip()
        if not msg:
            return {"error": "message required"}, 400
        if len(msg) > 2000:
            msg = msg[:2000]
        if not net.is_connected():
            return {"error": "ESP32 has no WiFi. Open /wifi."}, 503
        if not config.cfgEndpoint:
            return {"error": "agent endpoint not configured. Open /agent."}, 400
        hist = d.get("history", [])
        if not isinstance(hist, list):
            hist = []
        _sid, _log_path = _resolve_session(d.get("session"), activate=True)

        def _events():
            # D3 counters for the streaming path (best-effort wall time from
            # turn start to stream close; never breaks the stream). A streamed
            # turn that yields need_tools falls back to /api/chat, which owns
            # that turn and counts it again — once per request (see _STATS_*).
            _t0 = _doctor_now_ms()
            try:
                for _chunk in _events_inner():
                    yield _chunk
            finally:
                _stats_note_turn(_doctor_since_ms(_t0), _doctor_since_ms(_t0))

        def _events_inner():
            # Phase 8: this SSE path is intentionally OUTSIDE the shared
            # busy-guard (chat only: /api/chat + Telegram hold the mutex).
            # True upstream streaming: stream:true + incremental chunked
            # decode, re-emitted to the browser as it arrives. This was
            # previously avoided because stream:true "wedged the generator
            # forever" — that was the memory-starved standard firmware
            # (0.2 MB heap, 22 KB max contiguous block) failing to allocate
            # mbedTLS buffers mid-stream, not a protocol problem. On the
            # SPIRAM_OCT build it streams cleanly. Contract unchanged:
            # {"delta"} / {"reasoning"} events, {"need_tools":true} fallback
            # signal, then [DONE].
            import agent_tools
            import llm as _llm
            req = {"model": config.cfgModel, "temperature": 0.7, "max_tokens": 800,
                   "stream": True, "messages": []}
            msgs = req["messages"]
            # Phase 9: tiered Mini prompt (one build per request = frozen).
            msgs.append({"role": "system", "content": _system_prompt()})
            # Browser history is authoritative while the page is open; the
            # persisted log is the fallback for a fresh/refreshed page.
            if not hist:
                agent_tools.injectRecentLog(msgs, msg, 8, path=_log_path)
            _llm.addHistoryCapped(msgs, hist, 8)
            msgs.append({"role": "user", "content": msg[:1500]})
            agent_tools.addToolsArray(req)
            try:
                ubody = json.dumps(req)
            except Exception:
                yield 'data: {"error":"json encode failed"}\n\n'
                yield "data: [DONE]\n\n"
                return
            got_any = False
            ok = False
            err = ""
            code = 0
            parts = []
            for kind, val in _llm.streamChat(ubody):
                if kind == "delta":
                    got_any = True
                    parts.append(val)
                    yield "data: %s\n\n" % json.dumps({"delta": val})
                elif kind == "reasoning":
                    yield "data: %s\n\n" % json.dumps({"reasoning": val[:2000]})
                elif kind == "tools":
                    # Browser falls back to /api/chat, which runs the tool loop
                    # and persists that turn. Don't log a partial reply here.
                    yield 'data: {"need_tools":true}\n\n'
                    yield "data: [DONE]\n\n"
                    return
                elif kind == "status":
                    ok, err, code = val
            if not ok:
                yield 'data: %s\n\n' % json.dumps({"error": "upstream connect failed"})
                yield "data: [DONE]\n\n"
                return
            if code < 200 or code >= 300:
                eb = (err or "")[:400].replace('"', "'").replace("\n", " ")
                yield 'data: {"error":"upstream HTTP %d: %s"}\n\n' % (code, eb)
                yield "data: [DONE]\n\n"
                return
            if not got_any:
                yield 'data: {"need_tools":true}\n\n'
            else:
                # Persist the completed turn so a page refresh still has
                # context (same contract as the non-streaming /api/chat path).
                try:
                    agent_tools.appendChatLog(msg, "".join(parts), path=_log_path)
                except Exception as e:
                    print("[stream] log append failed:", str(e)[:80])
            yield "data: [DONE]\n\n"

        return _events(), {"Content-Type": "text/event-stream",
                           "Cache-Control": "no-cache", "Connection": "keep-alive"}

    # ---------- tools ----------
    @app.get("/api/tools")
    async def _get_tools(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        arr = []
        for i in range(len(agent_tools.TOOL_REGISTRY)):
            try:
                _t = agent_tools.TOOL_REGISTRY[i]
                _dflt_off = bool(_t.get("default_off"))
            except Exception:
                _dflt_off = False
            arr.append({"name": agent_tools.toolNameAt(i),
                        "label": agent_tools.toolUiHintAt(i),
                        "description": agent_tools.toolDescriptionAt(i),
                        "enabled": agent_tools.toolEnabledIdx(i),
                        "toolset": tool_toolset(agent_tools.toolNameAt(i)),
                        "default_off": _dflt_off})
        return {"tools": arr, "mask": config.gToolsMask,
                "prompt_preview": _system_prompt()[:600]}

    @app.post("/api/tools")
    async def _save_tools(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        mask = 0
        en = d.get("enabled")
        if isinstance(en, list):
            for n in en:
                i = agent_tools.toolIndex(str(n))
                if i >= 0:
                    mask |= (1 << i)
        elif "mask" in d:
            try:
                mask = int(d["mask"])
            except Exception:
                return {"error": "invalid mask"}, 400
        else:
            return {"error": "enabled[] required"}, 400
        config.saveToolsMask(mask)
        print("[tools] mask=%d" % mask)
        return {"ok": True, "mask": mask}

    # ---------- memory ----------
    @app.get("/api/memory")
    async def _get_memory(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        mem = ""
        try:
            mem = agent_tools.readMemoryFacts()[:3000]
        except Exception:
            pass
        # tail=N returns the last N chat-log lines. The default comes from
        # Config -> Chat history "Turns restored after reload" (x2 because a
        # turn is a user line + an assistant line). An explicit ?tail= still
        # overrides it for older clients/tools; hard cap 240 lines.
        try:
            import config as _cfg_mem
            default_tail = max(2, int(_cfg_mem.cfgChatRestoreTurns) * 2)
        except Exception:
            default_tail = 40
        tail_n = default_tail
        try:
            v = request.args.get("tail")
            if v is not None and str(v).strip():
                tail_n = max(1, min(240, int(v)))
        except Exception:
            tail_n = default_tail
        # ?session=<id> reads one conversation; blank = the active one.
        # ?activate=1 also persists that choice (Chat uses it on open).
        try:
            _want_sess = request.args.get("session", "") if hasattr(request, "args") else ""
        except Exception:
            _want_sess = ""
        try:
            _act = str(request.args.get("activate", "") if hasattr(request, "args") else "")
            _want_act = _act.strip().lower() in ("1", "true", "yes")
        except Exception:
            _want_act = False
        _sid, _log_path = _resolve_session(_want_sess, activate=_want_act)
        tail, log_bytes = _read_log_tail(_log_path, tail_n)
        out = {"memory": mem, "fs_ok": agent_tools.gFsOk,
               "session": _sid,
               "log_bytes": log_bytes, "log_tail": tail}
        # ?q= keyword search over current + rotated logs (Phase 4 sessions).
        # Kept alongside ?tail=: tail restores the transcript, q recalls
        # pre-/new turns that tail (current log only) cannot see.
        try:
            qv = request.args.get("q", "") if hasattr(request, "args") else ""
            if not str(qv or "").strip():
                qv = request.args.get("query", "") if hasattr(request, "args") else ""
        except Exception:
            qv = ""
        qv = str(qv or "").strip()
        if qv:
            try:
                lim = int(request.args.get("limit", "5") or "5")
            except Exception:
                lim = 5
            try:
                import sessions as _sess_q
                out["search"] = _sess_q.search(qv, lim)
            except Exception as e:
                out["search"] = {"success": False,
                                 "error": "search failed: %s" % str(e)[:80]}
        # ?pending=1 lists staged write-approval records (Phase 2).
        try:
            pv = request.args.get("pending", "")
            want_pending = str(pv).lower() in ("1", "true", "yes")
        except Exception:
            want_pending = False
        if want_pending:
            try:
                import memory as _mm
                out["pending"] = _mm.list_pending()
            except Exception:
                out["pending"] = []
        return out

    @app.post("/api/memory")
    async def _save_memory(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        # Write-approval review ops (Phase 2): pending list + approve/reject
        # by id or "all". Legacy clear_log/clear_memory/text flow below kept.
        try:
            op = str(d.get("op", "") or "").strip().lower()
        except Exception:
            op = ""
        if op in ("pending", "list_pending") or d.get("pending") is True:
            try:
                import memory as _mm
                return {"ok": True, "pending": _mm.list_pending()}
            except Exception as e:
                return {"error": "pending failed: %s" % str(e)[:80]}, 500
        if op in ("approve", "reject"):
            try:
                import memory as _mm
                sel = d.get("ids", d.get("id", "all"))
                if isinstance(sel, str) and sel.strip().lower() == "all":
                    sel = "all"
                res = (_mm.approve(sel) if op == "approve" else _mm.reject(sel))
                res["ok"] = bool(res.get("success"))
                return res
            except Exception as e:
                return {"error": "%s failed: %s" % (op, str(e)[:80])}, 500
        out = {}
        if d.get("clear_log"):
            # Legacy alias for "start a new conversation". The old single-log
            # rotation (chatlog -> chatlog.prev, which DELETED the previous
            # .prev) is gone: sessions live in opt/data/sessions and a new
            # one never destroys an existing conversation.
            try:
                import sessions as _sess_n
                out["session"] = _sess_n.new_session()
                out["rotated"] = True
            except Exception:
                out["rotated"] = False
            out["cleared_log"] = True
        if d.get("clear_memory"):
            try:
                import os
                os.remove(agent_tools.MEM_PATH)
            except OSError:
                pass
            out["cleared_memory"] = True
        # Phase 9: user-store wipe, symmetric with the device-store clear.
        # Accepts {"clear_user":true} or {"op":"clear_user"}.
        try:
            _want_user = bool(d.get("clear_user")) or op == "clear_user"
        except Exception:
            _want_user = False
        if _want_user:
            try:
                import memory as _mm_user
                _upath = _mm_user.USER_PATH
            except Exception:
                _upath = "opt/data/user.txt"
            try:
                import os
                os.remove(_upath)
            except OSError:
                pass
            out["cleared_user"] = True
        t = str(d.get("text", "") or "")
        if t:
            try:
                out["saved"] = bool(agent_tools.appendMemoryFact(t))
            except Exception:
                out["saved"] = False
        out["ok"] = True
        try:
            out["memory"] = agent_tools.readMemoryFacts()[:2000]
        except Exception:
            out["memory"] = ""
        return out

    # ---------- skills (Phase 3: L0 index in prompt, full text on demand) ----------
    @app.get("/api/skills")
    async def _get_skills(request):
        na = need_auth(request)
        if na:
            return na
        import skillstore as _sk
        try:
            qn = request.args.get("name", "") if hasattr(request, "args") else ""
        except Exception:
            qn = ""
        qn = str(qn or "").strip()
        if qn:
            if qn.startswith("bundle:"):
                return _sk.expand_bundle(qn[7:].strip())
            return _sk.view(qn)
        out = {"skills": _sk.index(), "bundles": _sk.list_bundles()}
        try:
            out["count"] = len(out["skills"])
        except Exception:
            out["count"] = 0
        try:
            pv = request.args.get("pending", "") if hasattr(request, "args") else ""
            want_pending = str(pv).lower() in ("1", "true", "yes")
        except Exception:
            want_pending = False
        if want_pending:
            try:
                out["pending"] = _sk.list_pending()
            except Exception:
                out["pending"] = []
        return out

    @app.post("/api/skills")
    async def _post_skills(request):
        na = need_auth(request)
        if na:
            return na
        import skillstore as _sk
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        try:
            act = str(d.get("action", d.get("op", "list")) or "list").strip().lower()
        except Exception:
            act = "list"
        if act in ("pending", "list_pending") or d.get("pending") is True:
            try:
                return {"ok": True, "pending": _sk.list_pending(),
                        "skills": _sk.index(), "bundles": _sk.list_bundles()}
            except Exception as e:
                return {"error": "pending failed: %s" % str(e)[:80]}, 500
        if act in ("approve", "reject"):
            try:
                sel = d.get("ids", d.get("id", "all"))
                if isinstance(sel, str) and sel.strip().lower() == "all":
                    sel = "all"
                res = (_sk.approve(sel) if act == "approve" else _sk.reject(sel))
                res["ok"] = bool(res.get("success"))
                return res
            except Exception as e:
                return {"error": "%s failed: %s" % (act, str(e)[:80])}, 500
        if act in ("list", "index", "get"):
            name = str(d.get("name", "") or "").strip()
            if name:
                if name.startswith("bundle:"):
                    return _sk.expand_bundle(name[7:].strip())
                return _sk.view(name)
            return {"ok": True, "skills": _sk.index(),
                    "bundles": _sk.list_bundles()}
        if act == "create":
            res = _sk.create(str(d.get("name", "") or ""),
                             str(d.get("content", d.get("text", "")) or ""))
            res["ok"] = bool(res.get("success"))
            return res
        if act in ("stage_draft", "stage", "propose"):
            res = _sk.propose(str(d.get("name", "") or ""),
                              str(d.get("content", d.get("text", "")) or ""))
            res["ok"] = bool(res.get("success"))
            return res
        if act == "patch":
            res = _sk.patch(str(d.get("name", "") or ""),
                            str(d.get("old_text", d.get("old", "")) or ""),
                            str(d.get("content", d.get("new_text", d.get("new", ""))) or ""))
            res["ok"] = bool(res.get("success"))
            return res
        if act == "delete":
            res = _sk.delete(str(d.get("name", "") or ""))
            res["ok"] = bool(res.get("success"))
            return res
        return {"error": ("Unknown action '%s'. Use: list, get, create, patch, delete, "
                          "stage_draft, pending, approve, reject" % act[:40])}, 400

    # ---------- sessions (Phase 4: journey feed + trajectory export) ----------
    # Journey/trajectory accept the auth token as ?token= (plain <a> links
    # cannot set headers — same pattern as /api/files/download).
    def _journey_authed(request):
        if is_authenticated(request):
            return True
        try:
            q = request.args.get("token", "") if hasattr(request, "args") else ""
            if q and q.strip() == config.cfgAuthToken and len(config.cfgAuthToken or "") > 0:
                return True
        except Exception:
            pass
        return False

    def _journey_need_auth(request):
        if _journey_authed(request):
            return None
        return {"error": "auth required"}, 401

    @app.get("/api/journey")
    async def _get_journey(request):
        na = _journey_need_auth(request)
        if na:
            return na
        import sessions as _sess_j
        return _sess_j.journey()

    @app.get("/api/trajectory")
    async def _get_trajectory(request):
        na = _journey_need_auth(request)
        if na:
            return na
        try:
            fmt = request.args.get("format", "sharegpt") if hasattr(request, "args") else "sharegpt"
        except Exception:
            fmt = "sharegpt"
        fmt = str(fmt or "sharegpt").strip().lower()
        if fmt != "sharegpt":
            return {"error": ("unknown format '%s'. Only format=sharegpt is supported" % fmt[:40])}, 400
        import sessions as _sess_t
        return _sess_t.trajectory()

    # Sessions page feed: one row per CONVERSATION (a file in
    # opt/data/sessions), newest first. Separate from /api/trajectory so the
    # ShareGPT export keeps its exact shape.
    @app.get("/api/sessions")
    async def _get_sessions(request):
        na = _journey_need_auth(request)
        if na:
            return na
        import sessions as _sess_l
        try:
            lim = int(request.args.get("limit", "") or 0)
        except Exception:
            lim = 0
        if lim <= 0:
            lim = _sess_l.LIST_DEFAULT_LIMIT
        return _sess_l.list_sessions(lim)

    # A new conversation. No file until the first turn, so pressing New Chat
    # repeatedly cannot litter the store with empty sessions.
    @app.post("/api/sessions")
    async def _post_sessions_new(request):
        na = need_auth(request)
        if na:
            return na
        import sessions as _sess_n
        sid = _sess_n.new_session()
        return {"success": True, "session": sid,
                "path": _sess_n.path_for(sid)}

    @app.post("/api/sessions/activate")
    async def _post_sessions_activate(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        import sessions as _sess_a
        sid = _sess_a.safe_id(d.get("id"))
        if not sid:
            return {"error": "invalid session id"}, 400
        _sess_a.set_active(sid)
        return {"success": True, "session": sid}

    # Whole-conversation export for one Sessions row. Downloaded through a
    # plain <a>, which cannot set headers, so ?token= is accepted here (same
    # pattern as /api/files/download and /api/journey).
    @app.get("/api/sessions/export")
    async def _get_sessions_export(request):
        na = _journey_need_auth(request)
        if na:
            return na
        import sessions as _sess_x
        try:
            sid_q = request.args.get("id", "") if hasattr(request, "args") else ""
        except Exception:
            sid_q = ""
        res = _sess_x.export_text(sid_q)
        if not res.get("success"):
            return {"error": res.get("error", "export failed")}, 404
        name = "talaria-%s.txt" % res["id"]
        print("[sessions] export %s (%d messages)" % (res["id"], res["messages"]))
        return (res["text"], 200,
                {"Content-Type": "text/plain; charset=utf-8",
                 "Content-Disposition": 'attachment; filename="%s"' % name})

    # Delete one conversation. The id is a SESSION id now; the old turn ids
    # (chatlog.jsonl:0:1:abcdef) are refused by the sanitiser, so a stale
    # client cannot delete a file by accident.
    @app.post("/api/sessions/delete")
    async def _post_sessions_delete(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        import sessions as _sess_d
        try:
            tid = str(d.get("id", "") or "")
        except Exception:
            tid = ""
        res = _sess_d.delete_session(tid)
        try:
            res["ok"] = bool(res.get("success"))
        except Exception:
            pass
        if not res.get("success"):
            return res, 400
        return res

    # ---------- cron (Phase 5: <=5 scheduled agent turns, 60s tick) ----------
    @app.get("/api/cron")
    async def _get_cron(request):
        na = need_auth(request)
        if na:
            return na
        import cron as _cron
        return _cron.list_jobs()

    @app.post("/api/cron")
    async def _post_cron(request):
        na = need_auth(request)
        if na:
            return na
        import cron as _cron
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        # Same ops as the `cron` tool (add/list/edit/pause/resume/remove/run_now).
        # run_now runs a live agent turn inline (TLS, seconds) — like /api/chat.
        res = _cron.handle(d)
        try:
            res["ok"] = bool(res.get("success"))
        except Exception:
            pass
        return res

    # ---------- gateway (Phase 8: Telegram pairing + status) ----------
    @app.get("/api/gateway")
    async def _get_gateway(request):
        na = need_auth(request)
        if na:
            return na
        try:
            import gateway as _gw
            return _gw.status()
        except Exception as e:
            return {"error": "gateway unavailable: %s" % str(e)[:80]}, 500

    @app.post("/api/gateway")
    async def _post_gateway(request):
        na = need_auth(request)
        if na:
            return na
        try:
            import gateway as _gw
        except Exception as e:
            return {"error": "gateway unavailable: %s" % str(e)[:80]}, 500
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        # Same ops as the pairing API (status/allow/deny/reset_offset).
        # The bot token is file-only (edit tg.json on the device) and any
        # token key in the body is ignored, never stored.
        res = _gw.handle(d)
        try:
            res["ok"] = bool(res.get("success"))
        except Exception:
            pass
        if not res.get("success"):
            err = str(res.get("error", "gateway failed"))
            code = 400
            if "id is required" in err:
                code = 400
            return res, code
        return res

    # ---------- console logs (ring buffer fed by logbuf.install()) ----------
    @app.get("/api/logs")
    async def _get_logs(request):
        na = need_auth(request)
        if na:
            return na
        import logbuf
        try:
            since = int(request.args.get("since", "0") or "0")
        except Exception:
            since = 0
        try:
            limit = int(request.args.get("limit", "150") or "150")
        except Exception:
            limit = 150
        entries, seq = logbuf.get(since, limit)
        return {"entries": entries, "seq": seq, "count": len(entries)}

    @app.post("/api/logs/clear")
    async def _clear_logs(request):
        na = need_auth(request)
        if na:
            return na
        import logbuf
        seq = logbuf.clear()
        return {"ok": True, "seq": seq}

    # ---------- files (Explorer: locked to the user-data home) ----------
    # Hermes parity: the browser shows /opt/data only, never flash `/`.
    # Every path is mapped through _files_data_norm, so `/` lists the data
    # home, `/memory.txt` reads opt/data/memory.txt, and system code is
    # unreachable here by construction. Use /api/system/files/* for repairs.
    def _files_authed(request):
        if is_authenticated(request):
            return True
        # Downloads use plain <a> links which cannot set headers — accept the
        # same token as a query param there. fetch() callers use the header.
        try:
            q = request.args.get("token", "") if hasattr(request, "args") else ""
            if q and q.strip() == config.cfgAuthToken and len(config.cfgAuthToken or "") > 0:
                return True
        except Exception:
            pass
        return False

    def _files_need_auth(request):
        if _files_authed(request):
            return None
        return {"error": "auth required"}, 401

    @app.get("/api/files")
    async def _files_list(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "/") if hasattr(request, "args") else "/"
        except Exception:
            qp = "/"
        norm = _fs_norm(qp)
        if norm is None:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None:
            return {"error": "invalid path"}, 400
        _ensure_data_tree_best_effort()
        entries, err = _fs_list_dir(dnorm)
        if err:
            return {"error": err}, 404 if err == "not found" else 400
        return {"path": "/" + dnorm, "parent": _files_data_parent(dnorm),
                "entries": entries, "count": len(entries),
                "root": "/" + _DATA_ROOT, "locked_root": "/" + _DATA_ROOT,
                "can_change_path": True}

    @app.get("/api/files/content")
    async def _files_content(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "") if hasattr(request, "args") else ""
        except Exception:
            qp = ""
        norm = _fs_norm(qp)
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None or dnorm == _DATA_ROOT:
            return {"error": "invalid path"}, 400
        res, err, size = _fs_read_text(dnorm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err, "size": size}, code
        return {"path": "/" + dnorm, "size": res["size"],
                "truncated": res["truncated"], "content": res["content"]}

    @app.get("/api/files/download")
    async def _files_download(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "") if hasattr(request, "args") else ""
        except Exception:
            qp = ""
        norm = _fs_norm(qp)
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None or dnorm == _DATA_ROOT:
            return {"error": "invalid path"}, 400
        full = _fs_full(dnorm)
        if _fs_is_dir(full) is not False:
            return {"error": "not a file"}, 400
        try:
            with open(full, "rb") as f:
                data = f.read(_FS_MAX_WRITE + 1)
        except Exception as e:
            return {"error": "read failed: %s" % str(e)[:80]}, 404
        if len(data) > _FS_MAX_WRITE:
            return {"error": "file too large to download (%dB)" % len(data)}, 400
        name = dnorm.rsplit("/", 1)[-1]
        low = name.lower()
        ctype = "application/octet-stream"
        if low.endswith(".html") or low.endswith(".htm"):
            ctype = "text/html"
        elif low.endswith(".py") or low.endswith(".txt") or low.endswith(".md"):
            ctype = "text/plain; charset=utf-8"
        elif low.endswith(".json"):
            ctype = "application/json"
        elif low.endswith(".css"):
            ctype = "text/css"
        elif low.endswith(".js"):
            ctype = "application/javascript"
        disp = name.replace('"', "_")
        return data, 200, {"Content-Type": ctype,
                           "Content-Disposition": 'attachment; filename="%s"' % disp}

    @app.post("/api/files/save")
    async def _files_save(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None or dnorm == _DATA_ROOT:
            return {"error": "invalid path"}, 400
        # config.yaml lives at flash `/`, outside the locked home — it is
        # owned by the Config page and the system hatch, never by Files.
        if dnorm == config.CONFIG_PATH or dnorm == _DATA_ROOT + "/config.yaml":
            return {"error": "config.yaml lives outside /opt/data - edit it via the Config page"}, 400
        content = d.get("content", "")
        if not isinstance(content, str):
            return {"error": "content must be a string"}, 400
        try:
            import checkpoint as _cp_save
            _cp_save.backup(dnorm)  # best-effort .bak; write proceeds regardless
        except Exception:
            pass
        err = _fs_write_text(dnorm, content)
        if err:
            code = 400
            if err.startswith("file too large"):
                code = 413
            return {"error": err}, code
        return {"ok": True, "path": "/" + dnorm, "size": len(content.encode("utf-8"))}

    @app.post("/api/files/mkdir")
    async def _files_mkdir(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None or dnorm == _DATA_ROOT:
            return {"error": "invalid path"}, 400
        import os as _os
        cur = ""
        for seg in dnorm.split("/"):
            cur = seg if not cur else cur + "/" + seg
            if _fs_is_dir(_fs_full(cur)) is True:
                continue
            try:
                _os.mkdir(_fs_full(cur))
            except Exception as e:
                return {"error": "mkdir failed: %s" % str(e)[:80]}, 400
        return {"ok": True, "path": "/" + dnorm}

    @app.post("/api/files/delete")
    async def _files_delete(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        dnorm = _files_data_norm(norm)
        if dnorm is None or dnorm == _DATA_ROOT:
            return {"error": "invalid path"}, 400
        err = _fs_delete(dnorm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err}, code
        return {"ok": True, "path": "/" + dnorm}

    @app.post("/api/files/rename")
    async def _files_rename(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        src = _fs_norm(d.get("src", d.get("from", "")))
        dst = _fs_norm(d.get("dst", d.get("to", "")))
        if src is None or not src or dst is None or not dst:
            return {"error": "invalid src/dst"}, 400
        dsrc = _files_data_norm(src)
        ddst = _files_data_norm(dst)
        if dsrc is None or dsrc == _DATA_ROOT or ddst is None or ddst == _DATA_ROOT:
            return {"error": "invalid src/dst"}, 400
        if dsrc == ddst:
            return {"error": "src == dst"}, 400
        import os as _os
        if _fs_is_dir(_fs_full(dsrc)) is None:
            return {"error": "not found"}, 404
        if _fs_is_dir(_fs_full(ddst)) is not None:
            return {"error": "destination exists"}, 409
        err = _fs_ensure_parent(ddst)
        if err:
            return {"error": err}, 400
        try:
            _os.rename(_fs_full(dsrc), _fs_full(ddst))
        except Exception as e:
            return {"error": "rename failed: %s" % str(e)[:80]}, 400
        return {"ok": True, "src": "/" + dsrc, "dst": "/" + ddst}

    @app.post("/api/files/upload")
    async def _files_upload(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "/") if hasattr(request, "args") else "/"
        except Exception:
            qp = "/"
        dest = _fs_norm(qp)
        if dest is None:
            return {"error": "invalid path"}, 400
        dest = _files_data_norm(dest)
        if dest is None:
            return {"error": "invalid path"}, 400
        files = {}
        try:
            if getattr(request, "files", None):
                files = request.files or {}
        except Exception:
            files = {}
        if not files:
            files = _parse_multipart(request)
        if not files:
            return {"error": "no file uploaded (field 'file')"}, 400
        # A text field named path/dir inside the form overrides the query.
        for k in ("path", "dir"):
            if k in files:
                try:
                    fu = files[k]
                    fn = getattr(fu, "filename", "") or ""
                    if not fn:
                        raw = fu.read() if hasattr(fu, "read") else fu.content
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "ignore")
                        cand = _fs_norm(raw)
                        if cand is not None:
                            cand = _files_data_norm(cand)
                        if cand is not None:
                            dest = cand
                        del files[k]
                        break
                except Exception:
                    pass
        saved = []
        for _field, fu in files.items():
            try:
                fname = getattr(fu, "filename", "") or ""
            except Exception:
                fname = ""
            base = fname.replace("\\", "/").split("/")[-1].strip()
            if not base or base in (".", "..") or ".." in base:
                continue
            norm = ((dest + "/" + base) if dest else base)
            norm = _fs_norm(norm)
            if norm is None or not norm:
                continue
            norm = _files_data_norm(norm)
            if norm is None or norm == _DATA_ROOT:
                continue
            try:
                data = fu.read() if hasattr(fu, "read") else bytes(getattr(fu, "content", b"") or b"")
                if isinstance(data, str):
                    data = data.encode("utf-8")
            except Exception as e:
                return {"error": "read failed: %s" % str(e)[:80]}, 500
            if not data:
                continue
            if len(data) > _FS_MAX_WRITE:
                return {"error": "%s too large (%dB, max %dB)" % (base, len(data), _FS_MAX_WRITE)}, 413
            err = _fs_ensure_parent(norm)
            if err:
                return {"error": err}, 400
            try:
                import checkpoint as _cp_up
                _cp_up.backup(norm)  # best-effort .bak; write proceeds
            except Exception:
                pass
            try:
                with open(_fs_full(norm), "wb") as f:
                    f.write(data)
                saved.append("/" + norm)
            except Exception as e:
                return {"error": "write %s failed: %s" % (base, str(e)[:80])}, 500
        if not saved:
            return {"error": "no acceptable files"}, 400
        return {"ok": True, "saved": saved, "path": "/" + dest if dest else "/"}

    # ---------- system files (repair hatch: full flash, deliberate) ----------
    # `/api/files` is locked to /opt/data. This hatch exposes flash `/`
    # (server.py, boot.py, lib/, www/, config.yaml) for repairs. Same auth,
    # same 100/200KB caps, same .bak checkpoints — but a separate route + UI
    # surface so a normal Files click can never brick the device. config.yaml
    # edits validate + reload here (moved from /api/files/save); the Config
    # page remains the primary config editor.
    @app.get("/api/system/files")
    async def _sysfiles_list(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "/") if hasattr(request, "args") else "/"
        except Exception:
            qp = "/"
        norm = _fs_norm(qp)
        if norm is None:
            return {"error": "invalid path"}, 400
        entries, err = _fs_list_dir(norm)
        if err:
            return {"error": err}, 404 if err == "not found" else 400
        disp = "/" + norm if norm else "/"
        return {"path": disp, "parent": "/" + _fs_parent(norm) if norm else None,
                "entries": entries, "count": len(entries)}

    @app.get("/api/system/files/content")
    async def _sysfiles_content(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "") if hasattr(request, "args") else ""
        except Exception:
            qp = ""
        norm = _fs_norm(qp)
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        res, err, size = _fs_read_text(norm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err, "size": size}, code
        return {"path": "/" + norm, "size": res["size"],
                "truncated": res["truncated"], "content": res["content"]}

    @app.get("/api/system/files/download")
    async def _sysfiles_download(request):
        na = _files_need_auth(request)
        if na:
            return na
        try:
            qp = request.args.get("path", "") if hasattr(request, "args") else ""
        except Exception:
            qp = ""
        norm = _fs_norm(qp)
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        full = _fs_full(norm)
        if _fs_is_dir(full) is not False:
            return {"error": "not a file"}, 400
        try:
            with open(full, "rb") as f:
                data = f.read(_FS_MAX_WRITE + 1)
        except Exception as e:
            return {"error": "read failed: %s" % str(e)[:80]}, 404
        if len(data) > _FS_MAX_WRITE:
            return {"error": "file too large to download (%dB)" % len(data)}, 400
        name = norm.rsplit("/", 1)[-1]
        disp = name.replace('"', "_")
        return data, 200, {"Content-Type": "application/octet-stream",
                           "Content-Disposition": 'attachment; filename="%s"' % disp}

    @app.post("/api/system/files/save")
    async def _sysfiles_save(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        content = d.get("content", "")
        if not isinstance(content, str):
            return {"error": "content must be a string"}, 400
        if norm == config.CONFIG_PATH:
            try:
                import yamlish
                parsed = yamlish.loads(content)
                if not isinstance(parsed, dict) or not parsed:
                    return {"error": "config.yaml must be a non-empty YAML mapping"}, 400
            except Exception as e:
                return {"error": "invalid config.yaml: %s" % str(e)[:160]}, 400
        try:
            import checkpoint as _cp_sys
            _cp_sys.backup(norm)  # best-effort .bak; write proceeds regardless
        except Exception:
            pass
        err = _fs_write_text(norm, content)
        if err:
            code = 400
            if err.startswith("file too large"):
                code = 413
            return {"error": err}, code
        if norm == config.CONFIG_PATH:
            try:
                config.loadConfig()
            except Exception as e:
                return {"error": "saved but config reload failed: %s"
                                 % str(e)[:120]}, 500
            return {"ok": True, "path": "/" + norm,
                    "size": len(content.encode("utf-8")), "reloaded": True}
        return {"ok": True, "path": "/" + norm, "size": len(content.encode("utf-8"))}

    @app.post("/api/system/files/mkdir")
    async def _sysfiles_mkdir(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        import os as _os
        cur = ""
        for seg in norm.split("/"):
            cur = seg if not cur else cur + "/" + seg
            if _fs_is_dir(_fs_full(cur)) is True:
                continue
            try:
                _os.mkdir(_fs_full(cur))
            except Exception as e:
                return {"error": "mkdir failed: %s" % str(e)[:80]}, 400
        return {"ok": True, "path": "/" + norm}

    @app.post("/api/system/files/delete")
    async def _sysfiles_delete(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        norm = _fs_norm(d.get("path", ""))
        if norm is None or not norm:
            return {"error": "invalid path"}, 400
        # Never delete the data home itself through the hatch — use /api/reset.
        if norm == _DATA_ROOT or norm == "opt":
            return {"error": "refusing to delete /opt/data (use /api/reset)"}, 400
        err = _fs_delete(norm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err}, code
        return {"ok": True, "path": "/" + norm}

    @app.post("/api/system/files/rename")
    async def _sysfiles_rename(request):
        na = _files_need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        src = _fs_norm(d.get("src", d.get("from", "")))
        dst = _fs_norm(d.get("dst", d.get("to", "")))
        if src is None or not src or dst is None or not dst:
            return {"error": "invalid src/dst"}, 400
        if src == dst:
            return {"error": "src == dst"}, 400
        import os as _os
        if _fs_is_dir(_fs_full(src)) is None:
            return {"error": "not found"}, 404
        if _fs_is_dir(_fs_full(dst)) is not None:
            return {"error": "destination exists"}, 409
        err = _fs_ensure_parent(dst)
        if err:
            return {"error": err}, 400
        try:
            _os.rename(_fs_full(src), _fs_full(dst))
        except Exception as e:
            return {"error": "rename failed: %s" % str(e)[:80]}, 400
        return {"ok": True, "src": "/" + src, "dst": "/" + dst}

    # ---------- rollback (Phase 7: .bak snapshots kept by writes/uploads) ----------
    @app.get("/api/rollback")
    async def _rollback_list(request):
        na = need_auth(request)
        if na:
            return na
        import checkpoint as _cp
        return _cp.list_backups()

    @app.post("/api/rollback")
    async def _rollback_post(request):
        na = need_auth(request)
        if na:
            return na
        import checkpoint as _cp
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        # D5 prune: {"op": "prune", "keep": N} or {"prune": true, "keep": N}
        # or {"prune": {"keep": N}}. Keeps the N newest .bak snapshots,
        # deletes the rest, reports the freed count. Default keep = 4.
        try:
            _op = str(d.get("op", "") or "").strip().lower()
        except Exception:
            _op = ""
        _prune_arg = d.get("prune", None)
        if _op == "prune" or _prune_arg is not None:
            try:
                if isinstance(_prune_arg, dict):
                    _keep = _prune_arg.get("keep", d.get("keep", 4))
                else:
                    _keep = d.get("keep", 4)
            except Exception:
                _keep = 4
            res = _cp.prune(_keep)
            try:
                res["ok"] = bool(res.get("success"))
            except Exception:
                pass
            if not res.get("success"):
                return res, 400
            return res
        res = _cp.rollback(d.get("path", ""))
        try:
            res["ok"] = bool(res.get("success"))
        except Exception:
            pass
        if not res.get("success"):
            err = str(res.get("error", "rollback failed"))
            code = 404 if "no backup" in err else 400
            return res, code
        return res

    # ---------- reset ----------
    # VERIFIED SEMANTICS (D5): POST /api/reset is a FACTORY-WIPE + reboot —
    # it deletes every saved conversation (opt/data/sessions/*), the activity
    # log, agent_tools.MEM_PATH (opt/data/memory.txt) and config.CONFIG_PATH
    # (config.yaml: WiFi creds, API key, auth token), THEN machine.reset().
    # Legacy config.json / config.json.bak are removed too. No dashboard
    # button wires to it; the /system Restart card uses POST /api/reboot
    # (soft reset only).
    @app.post("/api/reset")
    async def _reset(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        try:
            import os
            paths = [agent_tools.active_log_path(), agent_tools.MEM_PATH,
                     config.CONFIG_PATH, config.LEGACY_CONFIG_PATH,
                     config.LEGACY_BACKUP_PATH]
            try:
                import sessions as _sess_r
                paths.append(_sess_r.ACTIVITY_PATH)
                paths.append(_sess_r.ACTIVITY_PREV_PATH)
                try:
                    _names = os.listdir(_sess_r.SESS_DIR)
                except Exception:
                    _names = []
                for _fn in _names:
                    try:
                        if isinstance(_fn, bytes):
                            _fn = _fn.decode()
                    except Exception:
                        continue
                    paths.append(_sess_r.SESS_DIR + "/" + _fn)
            except Exception:
                pass
            for p in paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
        except Exception:
            pass

        async def _rb():
            await asyncio.sleep(0.5)
            try:
                import machine
                machine.reset()
            except Exception:
                pass
        try:
            asyncio.create_task(_rb())
        except Exception:
            pass
        return {"ok": True, "rebooting": True}

    # ---------- reboot (D5: soft reset ONLY — wipes nothing) ----------
    # Unlike /api/reset (factory-wipe + reboot, see above), this only
    # reboots: config.yaml, opt/data/memory.txt+user.txt, every conversation
    # under opt/data/sessions/, opt/data/cron.json and opt/data/tg.json all
    # survive. The /system Restart card uses this endpoint.
    @app.post("/api/reboot")
    async def _reboot(request):
        na = need_auth(request)
        if na:
            return na

        async def _rb2():
            await asyncio.sleep(0.5)
            try:
                import machine
                machine.reset()
            except Exception:
                pass
        try:
            asyncio.create_task(_rb2())
        except Exception:
            pass
        return {"ok": True, "rebooting": True}

    # ---------- backup (D5: redacted state export, ?token= download) ----------
    # Backup downloads use plain <a> links which cannot set headers — accept
    # the same token as a query param (same pattern as /api/files/download
    # and /api/journey). fetch() callers use the header.
    def _backup_authed(request):
        if is_authenticated(request):
            return True
        try:
            q = request.args.get("token", "") if hasattr(request, "args") else ""
            if q and q.strip() == config.cfgAuthToken and len(config.cfgAuthToken or "") > 0:
                return True
        except Exception:
            pass
        return False

    def _backup_need_auth(request):
        if _backup_authed(request):
            return None
        return {"error": "auth required"}, 401

    @app.get("/api/backup")
    async def _get_backup(request):
        na = _backup_need_auth(request)
        if na:
            return na
        return _collect_backup()

    # ---------- update (.py file upload, MicroPython-native) ----------
    async def _handle_update_upload(request):
        # try microdot multipart extension first
        files = {}
        try:
            from microdot.multipart import with_form_data  # noqa (presence check)
            # manual fallback below also works; extension populates request.files
            # when the route is decorated — here we parse manually to avoid
            # requiring the decorator at import time.
        except Exception:
            pass
        try:
            if getattr(request, "files", None):
                files = request.files or {}
        except Exception:
            files = {}
        if not files:
            files = _parse_multipart(request)
        if not files:
            return {"error": "no file uploaded (field 'firmware')"}, 400
        saved = []
        for _field, fu in files.items():
            try:
                fname = getattr(fu, "filename", "") or _field
            except Exception:
                fname = _field
            # sanitise: no dirs, no hidden, allow .py/.html/.json/.txt/.mpy
            base = fname.replace("\\", "/").split("/")[-1].strip()
            if not base or base.startswith(".") or ".." in base:
                continue
            low = base.lower()
            if base in ("config.yaml", "config.yaml.tmp", "config.json",
                          "config.json.bak", "config.json.tmp", "memory.txt",
                          "user.txt", "chatlog.jsonl", "chatlog.prev.jsonl",
                          "cron.json", "tg.json", "pending_mem.json",
                          "bundles.json"):
                continue  # never overwrite settings/memory/skills-bundle state via /update
            if low.endswith(".bak"):
                continue  # checkpoint snapshots are managed via /api/rollback
            # NOTE (Phase 3): skills/*.md and pending_skills/*.json are NOT in this
            # tuple on purpose and still unreachable: /update strips directories
            # (basename-only) so pending_skills/ cannot be addressed, and .md is not
            # an accepted extension — skills are managed via /api/skills only.
            allowed = low.endswith((".py", ".html", ".json", ".txt", ".mpy",
                                    ".js", ".css", ".svg", ".md"))
            if not allowed:
                # keep original .bin behaviour: reject with clear message
                return {"error": "only .py/.html/.json/.txt/.mpy/.js/.css/.svg/.md accepted (got %s)" % base[:40]}, 400
            # destination: web assets into www/assets/, other html into www/,
            # application code into app/ (only boot.py/main.py stay at root).
            # basename-only, so subdirectories cannot be addressed.
            if low.endswith((".js", ".css")):
                dest = "www/assets/" + base
            elif low.endswith((".html", ".svg", ".md")):
                dest = "www/" + base
            elif base in ("boot.py", "main.py"):
                dest = base
            else:
                dest = "app/" + base
                if low.endswith(".py"):
                    # Basename-only uploads cannot address subdirectories, so
                    # a tool file (app/tools/<base>) would land as a stray in
                    # app/. Route it to the existing home when there is one.
                    try:
                        import os as _os
                        _os.stat("app/tools/" + base)
                        dest = "app/tools/" + base
                    except Exception:
                        pass
            if (dest in ("boot.py", "main.py") or dest.startswith("app/")
                    or dest.startswith("www/")):
                pass  # allowed: entry points + app code + pages
            try:
                data = fu.read() if hasattr(fu, "read") else bytes(getattr(fu, "content", b"") or b"")
                if isinstance(data, str):
                    data = data.encode()
            except Exception as e:
                return {"error": "read failed: %s" % str(e)[:80]}, 500
            if not data:
                continue
            # Bundles are big; everything else keeps the old 200 KB ceiling.
            max_bytes = 900000 if low.endswith((".js", ".css")) else 200000
            if len(data) > max_bytes:
                return {"error": "%s too large (%dB, max %dKB)"
                                 % (base, len(data), max_bytes // 1000)}, 400
            try:
                with open(dest, "wb") as f:
                    f.write(data)
                saved.append(dest)
            except Exception as e:
                return {"error": "write %s failed: %s" % (dest, str(e)[:80])}, 500
        if not saved:
            return {"error": "no acceptable files"}, 400

        async def _rb():
            await asyncio.sleep(0.6)
            try:
                import machine
                machine.reset()
            except Exception:
                pass
        try:
            asyncio.create_task(_rb())
        except Exception:
            pass
        return {"ok": True, "saved": saved, "rebooting": True}

    # register /update POST with optional multipart decorator
    try:
        from microdot.multipart import with_form_data

        @app.post("/update")
        @with_form_data
        async def _update_post(request):
            if not is_authenticated(request):
                return "auth required", 401
            res = await _handle_update_upload(request)
            if isinstance(res, tuple):
                body, code = res
                if isinstance(body, dict):
                    return body, code
                return body, code
            if isinstance(res, dict) and res.get("error"):
                return res, 400
            return res
    except Exception:

        @app.post("/update")
        async def _update_post(request):
            if not is_authenticated(request):
                return "auth required", 401
            res = await _handle_update_upload(request)
            if isinstance(res, tuple):
                return res
            if isinstance(res, dict) and res.get("error"):
                return res, 400
            return res

    # ---------- UI bundle upload ----------
    # Convenience endpoint so a rebuilt dashboard can be pushed without a
    # serial cable:
    #     curl -X POST --data-binary @www/assets/app.js \
    #          -H "Authorization: Bearer <token>" \
    #          "http://<device>/api/ui/asset?path=assets/app.js"
    # Only the three web-root files are writable, and the body size is capped
    # just above a real bundle.
    @app.post("/api/ui/asset")
    async def _ui_asset(request):
        na = need_auth(request)
        if na:
            return na
        try:
            target = request.args.get("path", "") if hasattr(request, "args") else ""
        except Exception:
            target = ""
        safe = _www_safe(str(target or ""))
        if safe is None:
            return {"error": "path must be index.html, favicon.svg or assets/<file>"}, 400
        raw = request.body
        if raw is None:
            return {"error": "empty body"}, 400
        if isinstance(raw, str):
            raw = raw.encode()
        if len(raw) > 900000:
            return {"error": "too large (%dB, max 900000)" % len(raw)}, 413
        try:
            with open(_WWW + safe, "wb") as f:
                f.write(raw)
        except Exception as e:
            return {"error": "write failed: %s" % str(e)[:80]}, 500
        print("[ui] wrote %s (%d bytes)" % (safe, len(raw)))
        return {"ok": True, "path": "/" + safe, "size": len(raw)}

    # ---------- captive portal ----------
    @app.errorhandler(404)
    async def _not_found(request):
        if net.apMode:
            host = ""
            try:
                host = request.headers.get("Host", "") or ""
            except Exception:
                pass
            if "192.168.4.1" not in host:
                return Response.redirect("http://192.168.4.1/wifi")
        return "Not found. Try /, /files, /stats, /journey, /setup, /wifi, /agent, /functions, /docs, /update, /keys, /api/status, /api/stats, /api/journey, /api/trajectory, /api/logs", 404

    # ---------- SPA fallback (must be last) ----------
    # Every non-API path renders the shell; the client router owns the path.
    # Registered after all /api routes so they always win.
    @app.get("/<path:path>")
    async def _spa(request, path):
        if path.startswith("api/"):
            return {"error": "not found"}, 404
        res = _serve_www(path)
        if res is not None:
            return res
        res = _serve_www("index.html", cache="no-cache")
        if res is None:
            return "UI bundle missing. Deploy www/index.html and www/assets/.",
        return res

    _app = app
    return app


def _parse_multipart(request):
    """Minimal multipart/form-data parser. Returns {field: FileUpload-like}."""
    try:
        ctype = request.headers.get("Content-Type", "") or ""
    except Exception:
        return {}
    if "multipart/form-data" not in ctype:
        return {}
    import re as _re
    m = _re.search(r"boundary=([^\s;]+)", ctype)
    if not m:
        return {}
    boundary = m.group(1).strip().strip('"')
    try:
        raw = request.body
        if raw is None:
            return {}
        if isinstance(raw, str):
            raw = raw.encode()
    except Exception:
        return {}
    out = {}
    sep = ("--" + boundary).encode()

    class _FU:
        def __init__(self, filename, content):
            self.filename = filename
            self.content = content

        def read(self):
            return self.content

    for chunk in raw.split(sep):
        if not chunk or chunk in (b"--", b"--\r\n", b"\r\n"):
            continue
        # strip leading CRLF
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if chunk.endswith(b"--"):
            chunk = chunk[:-2]
        hb = chunk.find(b"\r\n\r\n")
        if hb < 0:
            continue
        headers = chunk[:hb].decode("utf-8", "ignore")
        content = chunk[hb + 4:]
        # strip trailing CRLF of content
        if content.endswith(b"\r\n"):
            content = content[:-2]
        fn = ""
        fm = _re.search(r'filename="([^"]*)"', headers)
        if fm:
            fn = fm.group(1)
        nm = ""
        nm_m = _re.search(r'name="([^"]*)"', headers)
        if nm_m:
            nm = nm_m.group(1)
        key = fn or nm or "file"
        # original UI field is 'firmware'
        out[nm or fn or "file"] = _FU(fn or nm, content)
        _ = key
    return out
