# gateway.py — Mini Hermes Phase 8: unified web + Telegram ingress.
# MicroPython-safe: utf-8 only, no `re`, bounded reads, lazy imports
# (`os`/`socket`/`ssl`/`gc`/`agent_core` inside functions), writes only on
# state change (never when idle/dormant).
#
# Surfaces share one agent turn at a time:
#   - session keys `mini:{platform}:{chat}` via sessions.session_key()
#     (web chat = `mini:web:default`; Telegram = `mini:telegram:<chat_id>`).
#   - per-key busy-guard `_INFLIGHT`: a second message for the same session
#     gets a "working" receipt and its text is stashed; the stash is injected
#     into the NEXT turn's context.
#   - global single-turn mutex `_GLOBAL_BUSY`: upstream TLS + heap mean two
#     concurrent turns (web + Telegram) risk a heap wedge, so the second
#     surface gets "busy, try again" (simple, safe). server.py /api/chat
#     acquires the same guard via acquire()/release().
#     NOTE: /api/chat-stream is intentionally NOT guarded (chat only) — SSE
#     streams bypass this mutex; documented, accepted hole.
#
# Pairing: tg.json {"bot_token": "", "allow": [], "requests": [], "offset": 0}
# (gitignored, /update-blocked, read_file/write_file-refused — token is
# file-only, NEVER settable via /api/gateway). Unknown Telegram chats get a
# "not paired" reply and their id is recorded in requests[] (bounded 20) for
# owner review via GET /api/gateway.
#
# Telegram transport is raw-socket (urequests has no timeout on MicroPython),
# same discipline as llm._post_raw / cron._post: IPv4-first DNS, socket
# timeout set BEFORE ssl.wrap_socket (SSLSocket has no settimeout), gc around
# the socket, small buffers, single attempt (the 30s poller retries), never
# raises — (ok, data) tuples only. _split_url/_send_all are deliberately
# DUPLICATED here (~40 lines) instead of factored into a shared helper: the
# llm/cron copies are flight-proven and a refactor risks all three callers.
try:
    import ujson as json
except ImportError:
    import json

import sessions

TG_PATH = "tg.json"
TG_API = "https://api.telegram.org"
READ_CAP = 4096  # tg.json bound (token + small id lists)
TG_MAX_BODY = 16384  # getUpdates/sendMessage bodies are small
TG_HANDSHAKE_TIMEOUT = 8
TG_TIMEOUT = 15
SEND_SPLIT = 4000  # Telegram message cap is 4096; split below it
REQUESTS_MAX = 20  # unknown-chat requests[] bound (flash + RAM)
NOTES_MAX = 3  # stashed busy-notes per session (bounded RAM)
NOTE_CHARS = 200  # per-note truncation
POLL_TIMEOUT_S = 5  # getUpdates long-poll hold (single poll per ~30s tick)

BUSY_REPLY = ("working on it — your last message is still running. "
              "I queued this note and will pick it up next.")
NOT_PAIRED_REPLY = ("Not paired with this agent yet — your chat id was "
                    "logged for the owner to approve. Ask the owner to "
                    "allowlist you, then try again.")
GLOBAL_BUSY_REPLY = ("Busy with another chat right now — "
                     "try again in a moment.")
EMPTY_REPLY = "Empty message — send some text and I'll reply."

_INFLIGHT = {}  # session key -> True while its turn runs
_GLOBAL_BUSY = False  # True while ANY turn runs (single upstream turn)
_NOTES = {}  # session key -> [stashed busy-note strings]


def _reset_guards():
    """Clear the in-memory guards (host tests; never touches flash)."""
    try:
        _INFLIGHT.clear()
    except Exception:
        pass
    global _GLOBAL_BUSY
    _GLOBAL_BUSY = False
    try:
        _NOTES.clear()
    except Exception:
        pass


# ---------- tg.json state ----------

def _blank_state():
    return {"bot_token": "", "allow": [], "requests": [], "offset": 0}


def _id_norm(cid):
    """Chat ids stay comparable across JSON int/str round-trips."""
    try:
        return int(str(cid).strip())
    except Exception:
        pass
    try:
        return str(cid).strip()[:64]
    except Exception:
        return ""


def _id_eq(a, b):
    try:
        return str(a) == str(b)
    except Exception:
        return False


def _load_state():
    try:
        with open(TG_PATH, "r") as f:
            try:
                raw = f.read(READ_CAP + 1)
            except TypeError:
                raw = f.read()  # very old MicroPython read() takes no size
    except OSError:
        return _blank_state()
    except Exception:
        return _blank_state()
    try:
        d = json.loads((raw or "{}")[:READ_CAP])
    except Exception:
        return _blank_state()
    if not isinstance(d, dict):
        return _blank_state()
    st = _blank_state()
    try:
        st["bot_token"] = str(d.get("bot_token", "") or "")[:200]
    except Exception:
        pass
    for k in ("allow", "requests"):
        try:
            items = d.get(k, [])
        except Exception:
            items = []
        if not isinstance(items, list):
            continue
        clean = []
        for v in items:
            n = _id_norm(v)
            if n == "" or n is None:
                continue
            dup = False
            for c in clean:
                if _id_eq(c, n):
                    dup = True
                    break
            if not dup:
                clean.append(n)
        st[k] = clean
    st["requests"] = st["requests"][:REQUESTS_MAX]
    try:
        st["offset"] = max(0, int(d.get("offset", 0) or 0))
    except Exception:
        st["offset"] = 0
    return st


def _save_state(st):
    try:
        doc = {"bot_token": st.get("bot_token", ""),
               "allow": st.get("allow", []),
               "requests": st.get("requests", [])[:REQUESTS_MAX],
               "offset": int(st.get("offset", 0) or 0)}
    except Exception:
        doc = _blank_state()
    with open(TG_PATH, "w") as f:
        f.write(json.dumps(doc))


def _is_allowed(st, chat_id):
    try:
        allow = st.get("allow", []) or []
    except Exception:
        return False
    for a in allow:
        if _id_eq(a, chat_id):
            return True
    return False


def _record_request(chat_id):
    """Log an unknown chat id for owner review (bounded). Best-effort."""
    try:
        st = _load_state()
    except Exception:
        return
    try:
        nid = _id_norm(chat_id)
    except Exception:
        return
    if nid == "" or nid is None:
        return
    try:
        reqs = st.get("requests", []) or []
        for r in reqs:
            if _id_eq(r, nid):
                return  # already listed — no rewrite (flash wear)
        reqs.append(nid)
        st["requests"] = reqs[-REQUESTS_MAX:]
        _save_state(st)
    except Exception:
        pass


# ---------- pairing API (owner) ----------

def allow_chat(chat_id):
    """Allowlist a chat (also clears it from requests[]). Never raises."""
    try:
        st = _load_state()
    except Exception as e:
        return {"success": False, "error": "load failed: %s" % str(e)[:80]}
    nid = _id_norm(chat_id)
    if nid == "" or nid is None:
        return {"success": False, "error": "chat id required"}
    try:
        if not _is_allowed(st, nid):
            st["allow"].append(nid)
        st["requests"] = [r for r in (st.get("requests", []) or [])
                          if not _id_eq(r, nid)]
        _save_state(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "allow": list(st["allow"])}


def deny_chat(chat_id):
    """Remove a chat from allow[] (and requests[]). Never raises."""
    try:
        st = _load_state()
    except Exception as e:
        return {"success": False, "error": "load failed: %s" % str(e)[:80]}
    try:
        st["allow"] = [a for a in (st.get("allow", []) or [])
                       if not _id_eq(a, chat_id)]
        st["requests"] = [r for r in (st.get("requests", []) or [])
                          if not _id_eq(r, chat_id)]
        _save_state(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "allow": list(st["allow"])}


def list_chats():
    """Allowlist + pairing requests + configured flag. Never leaks token."""
    try:
        st = _load_state()
    except Exception:
        st = _blank_state()
    try:
        configured = bool((st.get("bot_token", "") or "").strip())
    except Exception:
        configured = False
    try:
        off = int(st.get("offset", 0) or 0)
    except Exception:
        off = 0
    return {"success": True, "configured": configured,
            "allow": list(st.get("allow", []) or []),
            "requests": list(st.get("requests", []) or []),
            "offset": off}


def status():
    """GET /api/gateway body: presence only, never token content."""
    return list_chats()


def handle(d):
    """POST /api/gateway dispatcher. Never raises; token is file-only."""
    try:
        if not isinstance(d, dict):
            return {"success": False, "error": "args must be an object"}
        try:
            op = str(d.get("op", "status") or "status").strip().lower()
        except Exception:
            op = "status"
        note = ""
        for tk in ("bot_token", "token"):
            try:
                if tk in d and str(d.get(tk) or "").strip():
                    note = ("bot_token is file-only (edit tg.json on the "
                            "device); API value ignored")
                    break
            except Exception:
                pass
        if op in ("status", "list", "get"):
            r = status()
            if note:
                r["note"] = note
            return r
        if op == "allow":
            ids = []
            try:
                if "id" in d:
                    ids = [d.get("id")]
                elif "allow" in d and isinstance(d.get("allow"), list):
                    ids = d.get("allow")
                elif "ids" in d and isinstance(d.get("ids"), list):
                    ids = d.get("ids")
            except Exception:
                ids = []
            if not ids:
                return {"success": False,
                        "error": "id is required for 'allow'"}
            last = None
            for cid in ids:
                last = allow_chat(cid)
                if not last.get("success"):
                    return last
            last["note"] = note
            return last
        if op == "deny":
            try:
                cid = d.get("id", d.get("chat_id", ""))
            except Exception:
                cid = ""
            if cid == "" or cid is None:
                return {"success": False,
                        "error": "id is required for 'deny'"}
            r = deny_chat(cid)
            if note:
                r["note"] = note
            return r
        if op == "reset_offset":
            try:
                st = _load_state()
                st["offset"] = 0
                _save_state(st)
            except Exception as e:
                return {"success": False,
                        "error": "reset failed: %s" % str(e)[:80]}
            r = status()
            if note:
                r["note"] = note
            return r
        return {"success": False,
                "error": ("Unknown op '%s'. Use: status, allow, deny, "
                          "reset_offset" % op[:40])}
    except Exception as e:
        return {"success": False, "error": "gateway failed: %s" % str(e)[:120]}


# ---------- busy guards (shared web + Telegram) ----------

def acquire(key):
    """Take the per-key + global turn locks. Returns (ok, kind).

    kind "" when acquired; "note" when THIS key is busy (caller should
    stash + receipt); "global" when ANOTHER surface holds the turn
    (caller should refuse with busy-try-again). Never raises.
    """
    try:
        k = str(key or "")
    except Exception:
        k = ""
    if not k:
        return False, "global"
    try:
        if k in _INFLIGHT:
            return False, "note"
        global _GLOBAL_BUSY
        if _GLOBAL_BUSY:
            return False, "global"
        _INFLIGHT[k] = True
        _GLOBAL_BUSY = True
        return True, ""
    except Exception:
        return False, "global"


def release(key):
    """Release both locks. Never raises (double release is a no-op)."""
    try:
        _INFLIGHT.pop(str(key), None)
    except Exception:
        pass
    global _GLOBAL_BUSY
    try:
        if not _INFLIGHT:
            _GLOBAL_BUSY = False
    except Exception:
        _GLOBAL_BUSY = False


def _stash_note(key, text):
    try:
        lst = _NOTES.get(key)
        if not isinstance(lst, list):
            lst = []
            _NOTES[key] = lst
        lst.append(str(text or "")[:NOTE_CHARS])
        del lst[:-NOTES_MAX]
    except Exception:
        pass


def _take_notes(key):
    try:
        lst = _NOTES.pop(key, [])
    except Exception:
        lst = []
    if not isinstance(lst, list) or not lst:
        return ""
    try:
        return "; ".join(str(x) for x in lst)[:600]
    except Exception:
        return ""


# ---------- unified ingress ----------

def _default_run(key, text):
    import agent_core
    return agent_core.runTurn("[session %s] %s" % (key, text), [])


def handleIngress(platform, chat_id, text, run_fn=None):
    """One ingress path for web + Telegram. Returns the reply string.

    Web is always allowed; Telegram chats must be allowlisted (unknown ->
    "not paired" + id recorded). Same-key busy -> "working" receipt + note
    stashed for the next turn; other-surface busy -> try-again refusal.
    Default run is agent_core.runTurn with empty history plus a session
    note. Never raises (run_fn errors become "ERROR: ..." replies); the
    guard is always released via finally.
    """
    try:
        key = sessions.session_key(platform, chat_id)
    except Exception:
        key = "mini:web:default"
    try:
        msg = str(text if text is not None else "").strip()
    except Exception:
        msg = ""
    if not msg:
        return EMPTY_REPLY
    try:
        plat = str(platform if platform is not None else "web").strip().lower()
    except Exception:
        plat = "web"
    if not plat:
        plat = "web"
    if plat != "web":
        try:
            st = _load_state()
            allowed = _is_allowed(st, chat_id)
        except Exception:
            allowed = False
        if not allowed:
            _record_request(chat_id)
            return NOT_PAIRED_REPLY
    ok, kind = acquire(key)
    if not ok:
        if kind == "note":
            _stash_note(key, msg)
            return BUSY_REPLY
        return GLOBAL_BUSY_REPLY
    try:
        notes = _take_notes(key)
        full = msg
        if notes:
            full = msg + "\n[queued while you were busy: " + notes + "]"
        full = full[:1500]  # same user-message cap the agent turn applies
        fn = run_fn
        if fn is None:
            try:
                import agent_core as _ac
                fn = (lambda t: _ac.runTurn("[session %s] %s" % (key, t), []))
            except Exception:
                fn = _default_run_with_key(key)
        try:
            reply = fn(full)
        except Exception as e:
            reply = "ERROR: turn failed: %s" % str(e)[:120]
        if reply is None:
            reply = ""
        try:
            return str(reply)
        except Exception:
            return ""
    finally:
        release(key)


def _default_run_with_key(key):
    def _run(t):
        return _default_run(key, t)
    return _run


# ---------- Telegram transport (raw socket, never raises) ----------

def _split_url(url):
    # Deliberate duplicate of llm._split_url (see module docstring).
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


def _send_all(s, buf):
    # Deliberate duplicate of llm._send_all (see module docstring).
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


def _tg_http(method, path, token, body_text="", timeout=TG_TIMEOUT):
    """One raw-socket Bot API call. Test seam: monkeypatch this (no live
    network in tests). Returns (ok, text, code). Never raises."""
    try:
        url = TG_API + "/bot" + str(token) + str(path)
        is_https, host, port, ppath = _split_url(url)
    except Exception as e:
        return False, "bad url: %s" % str(e)[:60], 0
    try:
        import socket
    except ImportError:
        return False, "no socket", 0
    s = None
    try:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        s = socket.socket()
        try:
            s.settimeout(min(TG_HANDSHAKE_TIMEOUT, timeout))
        except Exception:
            pass
        try:
            import llm as _llm
            addrs = _llm._resolve_all_ipv4(host, port)
        except Exception:
            addrs = []
        if not addrs:
            try:
                infos = socket.getaddrinfo(host, port)
                addrs = [i[4] for i in infos]
            except Exception:
                return False, "dns failed for %s" % host[:60], 0
        if not addrs:
            return False, "no address for %s" % host[:60], 0
        s.connect(addrs[0])
        if is_https:
            try:
                import ssl as _sslmod
            except ImportError:
                try:
                    import ussl as _sslmod
                except ImportError:
                    return False, "no ssl", 0
            _wrap = getattr(_sslmod, "wrap_socket", None)
            if _wrap is not None:
                try:
                    s = _wrap(s, server_hostname=host)
                except TypeError:
                    s = _wrap(s)
            else:
                _ctx = _sslmod.create_default_context()
                try:
                    _ctx.check_hostname = False
                    _ctx.verify_mode = _sslmod.CERT_NONE
                except Exception:
                    pass
                s = _ctx.wrap_socket(s, server_hostname=host)
            # NOTE: no settimeout() on the wrapped socket — MicroPython's
            # SSLSocket has no settimeout (timeout was set pre-wrap above).
        if method == "GET":
            head = ("GET %s HTTP/1.0\r\nHost: %s\r\n"
                    "Accept: application/json\r\n"
                    "Connection: close\r\n\r\n" % (ppath, host))
            _send_all(s, head.encode())
        else:
            body = (body_text.encode("utf-8") if isinstance(body_text, str)
                    else body_text)
            head = ("POST %s HTTP/1.0\r\nHost: %s\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: %d\r\n"
                    "Connection: close\r\n\r\n" % (ppath, host, len(body)))
            _send_all(s, head.encode() + body)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            try:
                d = s.recv(1024)
            except Exception:
                break
            if not d:
                break
            buf += d
        if b"\r\n\r\n" not in buf:
            return False, "bad headers", 0
        shead, rest = buf.split(b"\r\n\r\n", 1)
        try:
            code = int(shead.split(b"\r\n", 1)[0].decode().split(" ")[1])
        except Exception:
            return False, "bad status", 0
        need = -1
        # Parse on BYTES: MicroPython's codec set is utf-8/ascii only
        # (decoding headers with any other codec fails — see llm._post_raw).
        for ln in shead.split(b"\r\n"):
            if ln[:15].lower() == b"content-length:":
                try:
                    need = int(ln[15:].strip())
                except Exception:
                    pass
        out = rest
        if need >= 0:
            while len(out) < need and len(out) < TG_MAX_BODY + 1024:
                try:
                    d = s.recv(1024)
                except Exception:
                    break
                if not d:
                    break
                out += d
            out = out[:need]
        else:
            while len(out) < TG_MAX_BODY:
                try:
                    d = s.recv(1024)
                except Exception:
                    break
                if not d:
                    break
                out += d
            out = out[:TG_MAX_BODY]
        return True, out.decode("utf-8", "ignore"), code
    except Exception as e:
        return False, str(e)[:120], 0
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def tg_poll(bot_token, offset=0):
    """GET getUpdates. Returns (True, {"updates": [...], "offset": next}) or
    (False, err). Malformed entries are skipped (never kill the poll).
    Never raises."""
    try:
        tok = str(bot_token or "")
    except Exception:
        tok = ""
    if not tok:
        return False, "no bot token"
    try:
        off = max(0, int(offset or 0))
    except Exception:
        off = 0
    path = "/getUpdates?offset=%d&timeout=%d" % (off, POLL_TIMEOUT_S)
    try:
        ok, text, code = _tg_http("GET", path, tok, "", TG_TIMEOUT)
    except Exception as e:
        return False, str(e)[:120]
    if not ok:
        try:
            return False, str(text)[:120]
        except Exception:
            return False, "poll failed"
    if code < 200 or code >= 300:
        return False, "HTTP %d" % code
    try:
        obj = json.loads(text)
    except Exception:
        return False, "bad JSON"
    try:
        if not isinstance(obj, dict) or not obj.get("ok"):
            return False, "telegram api not ok"
        res = obj.get("result", [])
    except Exception:
        return False, "bad result shape"
    if not isinstance(res, list):
        return False, "bad result shape"
    updates = []
    nxt = off
    for u in res:
        if not isinstance(u, dict):
            continue  # bad update skipped
        try:
            uid = int(u.get("update_id", -1))
        except Exception:
            continue
        if uid < 0:
            continue
        updates.append(u)
        if uid + 1 > nxt:
            nxt = uid + 1
    return True, {"updates": updates, "offset": nxt}


def tg_send(bot_token, chat_id, text):
    """POST sendMessage (plain text, no parse_mode), split at 4000 chars.
    Returns (True, {"sent": n, "chunks": m}) or (False, err). Never raises."""
    try:
        tok = str(bot_token or "")
    except Exception:
        tok = ""
    if not tok:
        return False, "no bot token"
    try:
        body = str(text if text is not None else "")
    except Exception:
        body = ""
    if not body.strip():
        return False, "empty text"
    try:
        cid = int(str(chat_id).strip())
    except Exception:
        try:
            cid = str(chat_id).strip()[:64]
        except Exception:
            return False, "bad chat id"
    chunks = [body[i:i + SEND_SPLIT] for i in range(0, len(body), SEND_SPLIT)]
    sent = 0
    for ch in chunks:
        try:
            payload = json.dumps({"chat_id": cid, "text": ch})
        except Exception:
            return False, "json encode failed"
        try:
            ok, _t, code = _tg_http("POST", "/sendMessage", tok,
                                    payload, TG_TIMEOUT)
        except Exception as e:
            return False, str(e)[:120]
        if not ok:
            try:
                return False, str(_t)[:120]
            except Exception:
                return False, "send failed"
        if code < 200 or code >= 300:
            return False, "HTTP %d" % code
        sent += 1
    return True, {"sent": sent, "chunks": len(chunks)}


# ---------- poller pass (main.py loops this every ~30s) ----------

def _parse_update(u):
    """(update_id, chat_id_or_None, text_or_None). Bad shapes -> None."""
    try:
        if not isinstance(u, dict):
            return None
        uid = int(u.get("update_id", -1))
    except Exception:
        return None
    if uid < 0:
        return None
    msg = None
    try:
        for k in ("message", "edited_message", "channel_post"):
            try:
                m = u.get(k)
            except Exception:
                m = None
            if isinstance(m, dict):
                msg = m
                break
    except Exception:
        msg = None
    if msg is None:
        return (uid, None, None)
    try:
        chat = msg.get("chat", {})
        cid = chat.get("id", None) if isinstance(chat, dict) else None
        if isinstance(cid, str) and cid.strip().lstrip("-").isdigit():
            cid = int(cid.strip())
    except Exception:
        cid = None
    try:
        t = msg.get("text", "")
        if not isinstance(t, str) or not t.strip():
            t = None
    except Exception:
        t = None
    return (uid, cid, t)


def _process_update(token, u):
    """One update: ingress + best-effort reply. Returns a small report dict."""
    p = _parse_update(u)
    if p is None:
        return {"success": False, "skipped": True}
    _uid, cid, text = p
    if cid is None or text is None:
        return {"success": True, "skipped": True}  # non-text/resolved: consume
    try:
        reply = handleIngress("telegram", cid, text)
    except Exception as e:
        return {"success": False, "error": "ingress failed: %s" % str(e)[:80]}
    try:
        ok, info = tg_send(token, cid, reply)
    except Exception as e:
        return {"success": True, "replied": False,
                "error": "send failed: %s" % str(e)[:80]}
    if ok:
        return {"success": True, "replied": True}
    try:
        return {"success": True, "replied": False,
                "error": "send failed: %s" % str(info)[:80]}
    except Exception:
        return {"success": True, "replied": False}


def tg_loop():
    """One poller pass. Dormant (no token): silent, no writes, no calls.
    Offset persists ONLY when it advances (flash wear). Per-update
    try/except: one bad update never kills the loop. Never raises."""
    try:
        st = _load_state()
    except Exception:
        return {"success": False, "error": "load failed"}
    try:
        token = str(st.get("bot_token", "") or "")
    except Exception:
        token = ""
    if not token:
        return {"success": True, "dormant": True, "processed": 0}
    try:
        offset = max(0, int(st.get("offset", 0) or 0))
    except Exception:
        offset = 0
    try:
        ok, data = tg_poll(token, offset)
    except Exception as e:
        return {"success": False, "error": "poll failed: %s" % str(e)[:80]}
    if not ok:
        try:
            err = str(data)[:120]
        except Exception:
            err = "poll failed"
        return {"success": False, "error": err}
    try:
        updates = data.get("updates", [])
        nxt = int(data.get("offset", offset) or offset)
    except Exception:
        updates, nxt = [], offset
    if not isinstance(updates, list):
        updates = []
    processed = 0
    for u in updates:
        try:
            _process_update(token, u)
        except Exception as e:
            try:
                print("[tg] bad update skipped: %s" % str(e)[:80])
            except Exception:
                pass
        try:
            processed += 1
        except Exception:
            pass
    if nxt > offset:
        try:
            st["offset"] = nxt
            _save_state(st)
        except Exception:
            pass
    return {"success": True, "dormant": False, "processed": processed,
            "offset": nxt}


# ---------- cron delivery ----------

def tg_send_result(reply, prompt="", jid=""):
    """Cron telegram delivery: broadcast to allowlisted chats. Returns
    (delivered, reason). No token -> the same delivered:false
    "telegram-phase-8" envelope cron reported before Phase 8. Lazy-import
    safe (cron imports this function lazily to avoid cycles). Never raises.
    """
    try:
        st = _load_state()
    except Exception:
        return False, "telegram-phase-8"
    try:
        token = str(st.get("bot_token", "") or "")
    except Exception:
        token = ""
    if not token:
        return False, "telegram-phase-8"
    try:
        allow = list(st.get("allow", []) or [])
    except Exception:
        allow = []
    if not allow:
        return False, "no telegram chats allowed"
    try:
        text = str(reply if reply is not None else "")
    except Exception:
        text = ""
    if not text.strip():
        return False, "empty reply"
    body = text[:500]  # same reply cap style as the webhook delivery
    ok_any = False
    last_err = ""
    for cid in allow:
        try:
            ok, info = tg_send(token, cid, body)
        except Exception as e:
            ok, info = False, str(e)[:80]
        if ok:
            ok_any = True
        else:
            try:
                last_err = str(info)[:120]
            except Exception:
                last_err = "send failed"
    if ok_any:
        return True, ""
    return False, (last_err or "send failed")
