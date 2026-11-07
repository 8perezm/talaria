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

_MODELS_MAX_IDS = 200
_MODELS_MAX_BYTES = 131072

# ---------- file manager (Explorer) helpers ----------
# Pure filesystem helpers (MicroPython-compatible: os.listdir/os.stat only).
# _FS_ROOT lets host tests point the tree at a tmp dir; on device it stays "".
_FS_ROOT = ""
_FS_MAX_READ = 100000
_FS_MAX_WRITE = 200000


def _fs_norm(p):
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
    norm = "/".join(parts)
    if len(norm) > 200:
        return None
    return norm


def _fs_full(norm):
    base = (_FS_ROOT or "").rstrip("/")
    if base:
        return base if not norm else base + "/" + norm
    return "/" + norm if norm else "/"


def _fs_parent(norm):
    if not norm or "/" not in norm:
        return ""
    return norm.rsplit("/", 1)[0]


def _fs_is_dir(full):
    import os
    try:
        st = os.stat(full)
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


def _fs_stat_size(full):
    import os
    try:
        return int(os.stat(full)[6])
    except Exception:
        return 0


def _fs_stat_mtime(full):
    import os
    try:
        st = os.stat(full)
        if len(st) > 8:
            return int(st[8])
    except Exception:
        pass
    return 0


def _fs_list_dir(norm):
    """Return (entries, err). entries=[{name,path,is_dir,size,mtime}]."""
    import os
    full = _fs_full(norm)
    if _fs_is_dir(full) is not True and norm != "":
        # root always listable; anything else must be a dir
        if _fs_is_dir(full) is None:
            return None, "not found"
        return None, "not a directory"
    names = []
    try:
        il = getattr(os, "ilistdir", None)
        if il is not None:
            for e in il(full):
                try:
                    n = e[0]
                except Exception:
                    continue
                if isinstance(n, bytes):
                    try:
                        n = n.decode()
                    except Exception:
                        continue
                if not n or n in (".", ".."):
                    continue
                names.append(n)
        else:
            for n in os.listdir(full):
                if isinstance(n, bytes):
                    try:
                        n = n.decode()
                    except Exception:
                        continue
                if not n or n in (".", ".."):
                    continue
                names.append(n)
    except Exception as e:
        return None, "list failed: %s" % str(e)[:80]
    try:
        names.sort(key=lambda s: s.lower())
    except Exception:
        names.sort()
    entries = []
    for n in names[:500]:
        child = (norm + "/" + n) if norm else n
        ff = _fs_full(child)
        d = _fs_is_dir(ff)
        is_dir = bool(d)
        entries.append({"name": n, "path": "/" + child, "is_dir": is_dir,
                        "size": 0 if is_dir else _fs_stat_size(ff),
                        "mtime": _fs_stat_mtime(ff)})
    return entries, ""


def _fs_read_text(norm, max_bytes=_FS_MAX_READ):
    import os
    full = _fs_full(norm)
    d = _fs_is_dir(full)
    if d is None:
        return None, "not found", 0
    if d:
        return None, "is a directory", 0
    size = _fs_stat_size(full)
    try:
        with open(full, "rb") as f:
            data = f.read(max_bytes + 1)
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


def _fs_ensure_parent(norm):
    """mkdir -p the parent chain of norm. Returns '' or err text."""
    import os
    parent = _fs_parent(norm)
    if not parent:
        return ""
    cur = ""
    for seg in parent.split("/"):
        cur = seg if not cur else cur + "/" + seg
        try:
            os.mkdir(_fs_full(cur))
        except Exception as e:
            # 17 = EEXIST on MicroPython/CPython; anything else on existing
            # dir is also fine — verify it is a dir before giving up.
            if _fs_is_dir(_fs_full(cur)) is not True:
                return "mkdir failed: %s" % str(e)[:80]
    return ""


def _fs_write_text(norm, content, max_bytes=_FS_MAX_WRITE):
    if not norm:
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
    err = _fs_ensure_parent(norm)
    if err:
        return err
    try:
        with open(_fs_full(norm), "wb") as f:
            f.write(data)
    except Exception as e:
        return "write failed: %s" % str(e)[:80]
    return ""


def _fs_delete(norm):
    """Delete a file or directory tree. Refuses root. Returns '' or err."""
    import os
    if not norm:
        return "refusing to delete /"
    full = _fs_full(norm)
    d = _fs_is_dir(full)
    if d is None:
        return "not found"
    if not d:
        try:
            os.remove(full)
        except Exception as e:
            return "delete failed: %s" % str(e)[:80]
        return ""
    # directory: iterative depth-first delete (no os.walk on MicroPython)
    stack = [norm]
    order = []
    while stack:
        cur = stack.pop()
        order.append(cur)
        entries, err = _fs_list_dir(cur)
        if err:
            return err
        for e in entries:
            child_norm = e["path"][1:]  # strip leading '/'
            if e["is_dir"]:
                stack.append(child_norm)
            else:
                try:
                    os.remove(_fs_full(child_norm))
                except Exception as ex:
                    return "delete failed: %s" % str(ex)[:80]
    for cur in reversed(order):
        try:
            os.rmdir(_fs_full(cur))
        except Exception as e:
            return "rmdir failed: %s" % str(e)[:80]
    return ""


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


def _read_log_tail(path, max_lines=10, max_chars=800):
    """Return (entries, bytes) for the last max_lines entries of the chat log.

    entries = [{"role": "user"|"assistant", "content": str}]. Shared by
    GET /api/memory (tail=N) and the chat page's transcript restore.
    """
    total = 0
    try:
        with open(path, "r") as f:
            all_text = f.read()
    except OSError:
        return [], 0
    total = len(all_text)
    lines = [ln for ln in all_text.split("\n") if ln.strip()]
    out = []
    for ln in lines[-max_lines:]:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        r = str(e.get("r", ""))[:20]
        c = str(e.get("c", ""))
        if not r or not c:
            continue
        out.append({"role": r, "content": c[:max_chars]})
    return out, total


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
            s["log_bytes"] = int(_os3.stat(_at.LOG_PATH)[6])
        except Exception:
            s["log_bytes"] = 0
        try:
            import os as _os4
            s["mem_bytes"] = int(_os4.stat(_at.MEM_PATH)[6])
        except Exception:
            s["mem_bytes"] = 0
        try:
            import os as _os5
            s["config_bytes"] = int(_os5.stat("config.json")[6])
        except Exception:
            s["config_bytes"] = 0
        try:
            _turns = 0
            with open(_at.LOG_PATH, "r") as _f:
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
            s["mdns"] = "http://" + _cfg.MDNS_NAME + ".local"
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
    return s


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
    @app.get("/")
    async def _index(request):
        if net.apMode and not config.cfgSsid:
            return Response.redirect("/wifi")
        return send_file("www/chat.html")

    @app.get("/setup")
    async def _setup(request):
        return send_file("www/setup.html")

    @app.get("/wifi")
    async def _wifi(request):
        return send_file("www/wifi.html")

    @app.get("/agent")
    async def _agent(request):
        return send_file("www/agent.html")

    @app.get("/update")
    async def _update(request):
        return send_file("www/update.html")

    @app.get("/functions")
    async def _funcs(request):
        return send_file("www/functions.html")

    @app.get("/docs")
    async def _docs(request):
        return send_file("www/docs.html")

    @app.get("/files")
    async def _files(request):
        return send_file("www/files.html")

    @app.get("/stats")
    async def _stats(request):
        return send_file("www/stats.html")

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
                log_bytes = os.stat(agent_tools.LOG_PATH)[6]
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

    @app.get("/api/auth")
    async def _get_auth(request):
        return {"auth_required": auth_enabled(), "ap_mode": net.apMode}

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
        return {"endpoint": config.cfgEndpoint, "model": config.cfgModel,
                "api_key_masked": config.maskedKey(config.cfgApiKey)}

    @app.post("/api/agent")
    async def _save_agent(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        ep = str(d.get("endpoint", "") or "").strip() or config.cfgEndpoint
        key = str(d.get("apiKey", d.get("api_key", "")) or "").strip()
        if not key:
            key = config.cfgApiKey
        model = str(d.get("model", "") or "").strip() or config.cfgModel or "gpt-4o-mini"
        if not ep:
            return {"error": "endpoint required"}, 400
        config.saveAgentOnly(ep, key, model)
        print("Saved agent: endpoint=%s model=%s (no reboot)" % (ep, model))
        return {"ok": True, "rebooting": False}

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
                "model": config.cfgModel, "api_key_masked": config.maskedKey(config.cfgApiKey)}

    @app.post("/api/config")
    async def _save_config(request):
        na = need_auth(request)
        if na:
            return na
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        hasWifi = "ssid" in d or "password" in d
        hasAgent = "endpoint" in d or "apiKey" in d or "api_key" in d or "model" in d
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
        out = {}
        # run blocking LLM loop in thread to keep server responsive (C++ blocks too)
        try:
            reply = _llm.callLLMWithTools(msg, hist, out)
        except Exception as e:
            reply = "ERROR: %s" % str(e)[:200]
        print("[chat] q=%d chars -> a=%d chars tools=[%s]" % (len(msg), len(reply), out.get("tools_used", "")))
        if reply.startswith("ERROR:"):
            code = 500
            if "HTTP 4" in reply:
                code = 502
            if "not configured" in reply:
                code = 400
            return {"error": reply}, code
        resp = {"reply": reply, "model": config.cfgModel}
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

        def _events():
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
            msgs.append({"role": "system", "content": agent_tools.buildSystemPrompt()})
            # Browser history is authoritative while the page is open; the
            # persisted log is the fallback for a fresh/refreshed page.
            if not hist:
                agent_tools.injectRecentLog(msgs, msg, 8)
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
                    agent_tools.appendChatLog(msg, "".join(parts))
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
            arr.append({"name": agent_tools.toolNameAt(i),
                        "label": agent_tools.toolUiHintAt(i),
                        "description": agent_tools.toolDescriptionAt(i),
                        "enabled": agent_tools.toolEnabledIdx(i)})
        return {"tools": arr, "mask": config.gToolsMask,
                "prompt_preview": agent_tools.buildSystemPrompt()[:600]}

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
        # tail=N returns the last N chat-log lines (default 10, capped 60).
        # The chat page uses ?tail=20 to rebuild the transcript after a refresh.
        tail_n = 10
        try:
            v = request.args.get("tail")
            if v is not None and str(v).strip():
                tail_n = max(1, min(60, int(v)))
        except Exception:
            tail_n = 10
        tail, log_bytes = _read_log_tail(agent_tools.LOG_PATH, tail_n)
        return {"memory": mem, "fs_ok": agent_tools.gFsOk,
                "log_bytes": log_bytes, "log_tail": tail}

    @app.post("/api/memory")
    async def _save_memory(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        d = _body_json(request)
        if d is None:
            return {"error": "invalid JSON"}, 400
        out = {}
        if d.get("clear_log"):
            try:
                import os
                os.remove(agent_tools.LOG_PATH)
            except OSError:
                pass
            out["cleared_log"] = True
        if d.get("clear_memory"):
            try:
                import os
                os.remove(agent_tools.MEM_PATH)
            except OSError:
                pass
            out["cleared_memory"] = True
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

    # ---------- files (Explorer: list / read / write / upload / download) ----------
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
        entries, err = _fs_list_dir(norm)
        if err:
            return {"error": err}, 404 if err == "not found" else 400
        disp = "/" + norm if norm else "/"
        return {"path": disp, "parent": "/" + _fs_parent(norm) if norm else None,
                "entries": entries, "count": len(entries)}

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
        res, err, size = _fs_read_text(norm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err, "size": size}, code
        return {"path": "/" + norm, "size": res["size"],
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
        content = d.get("content", "")
        if not isinstance(content, str):
            return {"error": "content must be a string"}, 400
        err = _fs_write_text(norm, content)
        if err:
            code = 400
            if err.startswith("file too large"):
                code = 413
            return {"error": err}, code
        return {"ok": True, "path": "/" + norm, "size": len(content.encode("utf-8"))}

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
        err = _fs_delete(norm)
        if err:
            code = 404 if err == "not found" else 400
            return {"error": err}, code
        return {"ok": True, "path": "/" + norm}

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
                with open(_fs_full(norm), "wb") as f:
                    f.write(data)
                saved.append("/" + norm)
            except Exception as e:
                return {"error": "write %s failed: %s" % (base, str(e)[:80])}, 500
        if not saved:
            return {"error": "no acceptable files"}, 400
        return {"ok": True, "saved": saved, "path": "/" + dest if dest else "/"}

    # ---------- reset ----------
    @app.post("/api/reset")
    async def _reset(request):
        na = need_auth(request)
        if na:
            return na
        import agent_tools
        try:
            import os
            for p in (agent_tools.LOG_PATH, agent_tools.MEM_PATH, config.CONFIG_PATH):
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
            if base in ("config.json", "memory.txt", "chatlog.jsonl", "config.json.tmp"):
                continue  # never overwrite settings/memory via /update
            allowed = low.endswith((".py", ".html", ".json", ".txt", ".mpy"))
            if not allowed:
                # keep original .bin behaviour: reject with clear message
                return {"error": "only .py/.html/.json/.txt/.mpy accepted (got %s)" % base[:40]}, 400
            # destination: www/ for html, root otherwise
            dest = ("www/" + base) if low.endswith(".html") else base
            if dest in ("boot.py", "main.py", "config.py", "agent_tools.py", "llm.py",
                        "net.py", "server.py") or dest.startswith("tools/") or dest.startswith("www/"):
                pass  # allowed: code + pages
            try:
                data = fu.read() if hasattr(fu, "read") else bytes(getattr(fu, "content", b"") or b"")
                if isinstance(data, str):
                    data = data.encode()
            except Exception as e:
                return {"error": "read failed: %s" % str(e)[:80]}, 500
            if not data:
                continue
            if len(data) > 200000:
                return {"error": "%s too large (%dB, max 200KB)" % (base, len(data))}, 400
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
        return "Not found. Try /, /files, /stats, /setup, /wifi, /agent, /functions, /docs, /update, /api/status, /api/stats, /api/logs", 404

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
