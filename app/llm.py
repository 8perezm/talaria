# llm.py — OpenAI-compatible bridge (non-stream + agentic tool loop).
# MicroPython port of src/llm.h/.cpp.
try:
    import ujson as json
except ImportError:
    import json


_LLM_TIMEOUT = 45
_LLM_TRIES = 4
_LLM_HANDSHAKE_TIMEOUT = 8


def _ticks_ms():
    try:
        import time as _t
        if hasattr(_t, "ticks_ms"):
            return _t.ticks_ms()
        return int(_t.time() * 1000)
    except Exception:
        return 0


def _ticks_diff(a, b):
    try:
        import time as _t
        if hasattr(_t, "ticks_diff"):
            return _t.ticks_diff(a, b)
    except Exception:
        pass
    return a - b
_LLM_MAX_BODY = 16384


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


_DNS_CACHE = {}
_DNS_TTL_MS = 600000


def _resolve_all_ipv4(host, port):
    """IPv4 connect() sockaddrs, cached 10 min (getaddrinfo has no timeout)."""
    now = _ticks_ms()
    try:
        ent = _DNS_CACHE.get(host)
        if ent is not None and ent[0] and (now - ent[1]) < _DNS_TTL_MS:
            return ent[0]
    except Exception:
        pass
    import socket
    try:
        infos = socket.getaddrinfo(host, port)
    except Exception:
        return []
    addrs = [i[4] for i in infos if i[0] == socket.AF_INET]
    if addrs:
        try:
            _DNS_CACHE[host] = (addrs, now)
        except Exception:
            pass
    return addrs


def _dns_invalidate(host):
    try:
        _DNS_CACHE.pop(host, None)
    except Exception:
        pass


def _resolve_ipv4(host, port):
    """Return a connect() sockaddr for host, preferring IPv4.

    The ESP often resolves AAAA first; connecting to an unreachable IPv6
    address blackholes until the socket timeout (47s observed). IPv4 first.
    """
    addrs = _resolve_all_ipv4(host, port)
    if not addrs:
        # fall back to whatever the resolver gave (may raise on connect)
        import socket
        infos = socket.getaddrinfo(host, port)
        if not infos:
            raise ValueError("no address for %s" % host)
        return infos[0][4]
    return addrs[0]


def _send_all(s, buf):
    """ussl.send() may partial-write large buffers — loop until all sent."""
    mv = memoryview(buf)
    sent = 0
    while sent < len(buf):
        n = s.send(mv[sent:])
        if n is None:
            continue
        if n <= 0:
            raise OSError("send stalled")
        sent += n


def _post_raw(url, reqBody, headers, timeout=_LLM_TIMEOUT, tries=_LLM_TRIES):
    """Raw-socket POST with explicit timeouts (urequests has none on MicroPython).

    HTTP/1.0 so the server sends Content-Length instead of chunked encoding.
    Handshake gets a short budget (normally 1-3s); response gets `timeout`.
    Retries whole attempt: TLS handshakes to some edges hang intermittently.
    Returns (True, text, code) or (False, err, 0).
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
    for attempt in range(max(1, tries)):
        try:
            import gc
            try:
                gc.collect()
            except Exception:
                pass
            s = socket.socket()
            try:
                s.settimeout(min(_LLM_HANDSHAKE_TIMEOUT, timeout))
            except Exception:
                pass
            # fresh DNS per attempt: round-robin may hand a different PoP,
            # and a lossy path to one PoP shouldn't doom every attempt.
            _t0 = _ticks_ms()
            _addrs = _resolve_all_ipv4(host, port)
            if not _addrs:
                raise ValueError("no address for %s" % host)
            s.connect(_addrs[attempt % len(_addrs)])
            _t1 = _ticks_ms()
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
                _t2 = _ticks_ms()
                print("[net] try%d conn=%dms tls=%dms" % (
                    attempt, _ticks_diff(_t1, _t0),
                    _ticks_diff(_t2, _t1)))
                # re-apply: some builds reset the timeout on the wrapped
                # socket, which would turn later recvs into infinite blocks.
                # Response phase gets the full budget (slow inference can be
                # silent for tens of seconds); handshake used the short one.
                try:
                    s.settimeout(timeout)
                except Exception:
                    pass
            body = reqBody.encode("utf-8") if isinstance(reqBody, str) else reqBody
            lines = ["POST %s HTTP/1.0" % path, "Host: %s" % host]
            for k, v in headers.items():
                lines.append("%s: %s" % (k, v))
            lines.append("Content-Length: %d" % len(body))
            lines.append("Connection: close")
            head = ("\r\n".join(lines) + "\r\n\r\n").encode()
            _send_all(s, head + body)
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 8192:
                d = s.recv(1024)
                if not d:
                    break
                buf += d
            if b"\r\n\r\n" not in buf:
                last_err, last_code = "bad headers", 0
            else:
                shead, rest = buf.split(b"\r\n\r\n", 1)
                try:
                    code = int(shead.split(b"\r\n", 1)[0].decode().split(" ")[1])
                except Exception:
                    code = 0
                if code == 0:
                    last_err, last_code = "bad status", 0
                else:
                    need = -1
                    # Parse on BYTES: MicroPython's codecs are minimal
                    # ('iso-8859-1' raises "unknown encoding", which broke
                    # every successful response). Headers are ASCII.
                    for ln in shead.split(b"\r\n"):
                        if ln[:15].lower() == b"content-length:":
                            try:
                                need = int(ln[15:].strip())
                            except Exception:
                                pass
                    out = rest
                    if need is not None and need >= 0:
                        while len(out) < need and len(out) < _LLM_MAX_BODY + 4096:
                            try:
                                d = s.recv(4096)
                            except Exception as e:
                                if not out:
                                    raise e
                                break
                            if not d:
                                break
                            out += d
                        out = out[:need]
                    else:
                        while len(out) < _LLM_MAX_BODY:
                            try:
                                d = s.recv(4096)
                            except Exception:
                                break
                            if not d:
                                break
                            out += d
                        out = out[:_LLM_MAX_BODY]
                    try:
                        s.close()
                    except Exception:
                        pass
                    s = None
                    return True, out.decode("utf-8", "ignore"), code
        except Exception as e:
            last_err = str(e)[:150]
            print("[net] post try%d fail: %s" % (attempt, last_err[:100]))
            # TLS buffer exhaustion (ENOMEM/EPERM, or a handshake that times
            # out because mbedTLS never got its record buffers) is not fixed
            # by retrying instantly: the previous socket's memory must be
            # reclaimed first. Yield the GIL/IDF heap, then back off briefly.
            _low = last_err
            if ("116" in _low or "1)" in _low or "ENOMEM" in _low
                    or "memory" in _low.lower() or "ETIMEDOUT" in _low):
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass
                try:
                    import time as _tm
                    _tm.sleep(0.35)
                except Exception:
                    pass
        finally:
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
            s = None
    _dns_invalidate(host)
    return False, last_err, last_code


class _ChunkedReader:
    """Decode a `Transfer-Encoding: chunked` body from a socket.

    Needed only for streaming: the buffered path uses HTTP/1.0, where servers
    must send Content-Length. SSE responses are HTTP/1.1 + chunked, so the
    stream path has to de-chunk incrementally.
    """

    def __init__(self, sock, buf):
        self.s = sock
        self.buf = buf
        self.done = False

    def _fill(self):
        d = self.s.recv(512)
        if not d:
            raise OSError("eof in chunked body")
        self.buf += d

    def read(self, n=512):
        out = b""
        while len(out) < n:
            if self.done:
                break
            idx = self.buf.find(b"\r\n")
            if idx < 0:
                self._fill()
                continue
            line = self.buf[:idx]
            try:
                size = int(line.split(b";")[0].strip() or b"0", 16)
            except Exception:
                raise OSError("bad chunk size")
            if size == 0:
                self.done = True
                break
            need = idx + 2 + size + 2
            while len(self.buf) < need:
                self._fill()
            out += self.buf[idx + 2: idx + 2 + size]
            self.buf = self.buf[need:]
        return out


def _stream_one_provider(reqBody, url, headers, timeout=_LLM_TIMEOUT,
                         tries=_LLM_TRIES):
    """Stream one provider attempt (tries socket retries). Generator of
    (kind, text) tuples; kinds 'delta' | 'reasoning' | 'tools' | 'status'.
    The final item is always ('status', (ok, err, code)). Factored out of
    streamChat so provider failover (and host tests) can drive it per
    provider without touching sockets.
    """
    try:
        is_https, host, port, path = _split_url(url)
    except Exception as e:
        yield ("status", (False, "bad url: %s" % str(e)[:80], 0))
        return
    import socket
    last_err, last_code = "no attempt", 0
    for attempt in range(max(1, tries)):
        s = None
        yielded = False
        try:
            import gc
            try:
                gc.collect()
            except Exception:
                pass
            s = socket.socket()
            try:
                s.settimeout(min(_LLM_HANDSHAKE_TIMEOUT, timeout))
            except Exception:
                pass
            addrs = _resolve_all_ipv4(host, port)
            if not addrs:
                raise ValueError("no address for %s" % host)
            s.connect(addrs[attempt % len(addrs)])
            if is_https:
                try:
                    import ssl as _sslmod
                except ImportError:
                    import ussl as _sslmod
                _wrap = getattr(_sslmod, "wrap_socket", None)
                if _wrap is not None:
                    try:
                        s = _wrap(s, server_hostname=host)
                    except TypeError:
                        s = _wrap(s)
                else:
                    _ctx = _sslmod.create_default_context()
                    _ctx.check_hostname = False
                    _ctx.verify_mode = _sslmod.CERT_NONE
                    s = _ctx.wrap_socket(s, server_hostname=host)
                try:
                    s.settimeout(timeout)
                except Exception:
                    pass
            body = reqBody.encode("utf-8") if isinstance(reqBody, str) else reqBody
            # HTTP/1.1 here (unlike the buffered path): SSE needs chunked
            # responses, which HTTP/1.0 servers cannot send.
            lines = ["POST %s HTTP/1.1" % path, "Host: %s" % host]
            for k, v in headers.items():
                lines.append("%s: %s" % (k, v))
            lines.append("Content-Length: %d" % len(body))
            lines.append("Connection: close")
            _send_all(s, ("\r\n".join(lines) + "\r\n\r\n").encode() + body)

            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 8192:
                d = s.recv(512)
                if not d:
                    break
                buf += d
            if b"\r\n\r\n" not in buf:
                raise OSError("bad headers")
            shead, rest = buf.split(b"\r\n\r\n", 1)
            try:
                code = int(shead.split(b"\r\n", 1)[0].decode().split(" ")[1])
            except Exception:
                code = 0
            if code == 0:
                raise OSError("bad status")
            if code < 200 or code >= 300:
                # Error bodies are small and JSON — hand them back verbatim.
                out = rest
                while len(out) < 600:
                    d = s.recv(512)
                    if not d:
                        break
                    out += d
                yield ("status", (True, out.decode("utf-8", "ignore"), code))
                return
            chunked = b"transfer-encoding: chunked" in shead.lower()
            reader = _ChunkedReader(s, rest) if chunked else None
            text = ""
            done = False
            while not done:
                if reader is not None:
                    d = reader.read(512)
                else:
                    d = s.recv(512)
                if not d:
                    break
                text += d.decode("utf-8", "ignore")
                while "\n" in text:
                    ln, text = text.split("\n", 1)
                    ln = ln.strip()
                    if not ln.startswith("data:"):
                        continue
                    payload = ln[5:].strip()
                    if not payload:
                        continue
                    if payload == "[DONE]":
                        done = True
                        break
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    try:
                        delta = obj["choices"][0].get("delta") or {}
                    except Exception:
                        continue
                    if not isinstance(delta, dict):
                        continue
                    if delta.get("tool_calls"):
                        yielded = True
                        yield ("tools", None)
                    rc = delta.get("content")
                    if rc:
                        yielded = True
                        yield ("delta", rc)
                    rr = (delta.get("reasoning_content")
                          or delta.get("reasoning") or "")
                    if rr:
                        yield ("reasoning", rr)
            yield ("status", (True, "", code))
            return
        except Exception as e:
            last_err = str(e)[:150]
            print("[net] stream try%d fail: %s" % (attempt, last_err[:100]))
            if yielded:
                # Mid-stream failure: report it, do not restart and duplicate.
                yield ("status", (False, last_err, 0))
                return
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            try:
                import time as _tm
                _tm.sleep(0.3)
            except Exception:
                pass
        finally:
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
    _dns_invalidate(host)
    yield ("status", (False, last_err, last_code))


def streamChat(reqBody, timeout=_LLM_TIMEOUT, tries=_LLM_TRIES):
    """Streaming chat/completions. Generator of (kind, text) tuples.

    kinds: 'delta' | 'reasoning' | 'tools' | 'status'
    The final item is always ('status', (ok, err, code)).
    Callers yield straight to the browser, so the first token reaches the UI
    in ~1s instead of after the whole completion.

    Provider failover: if the primary fails BEFORE any delta/tool event is
    yielded and a fallback is configured, the whole request is retried once
    on the fallback. Once anything is yielded, failures report in place —
    never restart mid-stream and duplicate output.
    """
    import config
    try:
        import providers as _prov
        plist = _prov.getProviders()
    except Exception:
        plist = []
    if not plist:
        url = config.chatCompletionsUrl(config.cfgEndpoint)
        for kind, val in _stream_one_provider(reqBody, url,
                                              _headers_for(config.cfgApiKey, True),
                                              timeout, tries):
            yield (kind, val)
        return
    yielded = False
    for pi, (_url, _key, _model) in enumerate(plist):
        body = _body_with_model(reqBody, _model)
        pending = None
        for kind, val in _stream_one_provider(body, _url,
                                              _headers_for(_key, True),
                                              timeout, tries):
            if kind == "delta" or kind == "tools":
                yielded = True
                yield (kind, val)
            elif kind == "status":
                pending = val
            else:
                yield (kind, val)
        if pending is None:
            pending = (False, "empty stream", 0)
        ok, err, code = pending
        if ok and 200 <= code < 300:
            yield ("status", pending)
            return
        if yielded:
            # Mid-stream failure (or error after output began): report it,
            # do not restart and duplicate.
            yield ("status", pending)
            return
        try:
            import providers as _p2
            retry = _p2.shouldFailover(ok, code)
        except Exception:
            retry = not ok
        if retry and pi + 1 < len(plist):
            print("[net] stream provider%d failed, failing over" % pi)
            continue
        yield ("status", pending)
        return


def _body_with_model(reqBody, model):
    """Return reqBody with its 'model' field swapped for a fallback provider.

    postLLM/streamChat receive a body already encoded with the primary model;
    the fallback entry may name a different model. Re-encode (same shape);
    on any failure return the body untouched. utf-8 only.
    """
    try:
        if isinstance(reqBody, bytes):
            reqBody = reqBody.decode("utf-8")
        if not model:
            return reqBody
        obj = json.loads(reqBody)
        if isinstance(obj, dict):
            if obj.get("model") == model:
                return reqBody
            obj["model"] = model
            return json.dumps(obj)
    except Exception:
        pass
    return reqBody


def _headers_for(api_key, stream=False):
    headers = {"Content-Type": "application/json",
               "HTTP-Referer": "http://talaria-agent.local", "X-Title": "Talaria-Agent"}
    headers["Accept"] = "text/event-stream" if stream else "application/json"
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    return headers


def postLLM(reqBody):
    """POST chat/completions. Returns (ok, resp_text, code).

    Tries the primary provider, then once the fallback (if configured).
    Failover on transport failure, HTTP 429, HTTP 5xx. Other statuses
    (incl. 401) and bad JSON return immediately, as before.
    """
    import config
    try:
        import providers as _prov
        plist = _prov.getProviders()
    except Exception:
        plist = []
    if not plist:
        url = config.chatCompletionsUrl(config.cfgEndpoint)
        return _post_raw(url, reqBody, _headers_for(config.cfgApiKey))
    last = (False, "no provider", 0)
    for i, (_url, _key, _model) in enumerate(plist):
        body = _body_with_model(reqBody, _model)
        ok, resp, code = _post_raw(_url, body, _headers_for(_key))
        last = (ok, resp, code)
        try:
            import providers as _p2
            retry = _p2.shouldFailover(ok, code)
        except Exception:
            retry = not ok
        if retry and i + 1 < len(plist):
            print("[net] provider%d failed (%s), failing over" % (i, str(resp)[:60]))
            continue
        return ok, resp, code
    return last


def addHistoryCapped(msgs, history, maxTurns=8):
    if not history:
        return
    count = 0
    for m in history:
        if count >= maxTurns * 2:
            break
        if not isinstance(m, dict):
            continue
        r = m.get("role", "")
        c = m.get("content", "")
        if not r or not c:
            continue
        if r not in ("user", "assistant", "system"):
            continue
        count += 1
        msgs.append({"role": r, "content": str(c)[:1500]})


def _msg_text(msg):
    if not isinstance(msg, dict):
        return "", "", ""
    content = msg.get("content", "") or ""
    rc = msg.get("reasoning_content", "") or msg.get("reasoning", "") or ""
    rd = ""
    try:
        det = msg.get("reasoning_details")
        if isinstance(det, list) and det and isinstance(det[0], dict):
            rd = det[0].get("text", "") or ""
    except Exception:
        pass
    reason = rc or rd
    return content, reason, rd


def callLLMWithTools(userMsg, history=None, out=None, max_iters=None,
                     log_path=None):
    """Agentic loop. Returns reply string (or 'ERROR: ...').

    out, if a dict, is filled with {'reasoning': str, 'tools_used': str}.
    max_iters caps the tool-call rounds (default from config.agent_max_iters,
    clamped 1..5). The system prompt is built ONCE per turn (frozen) and
    reused across iterations.

    log_path names the conversation file this turn belongs to (a session for
    web/Telegram, the activity log for cron). None keeps the legacy default
    (agent_tools.LOG_PATH) so older callers and host tests are unaffected.
    """
    import config
    import agent_tools
    try:
        import prompt as _promptmod
        _build_prompt = _promptmod.buildMiniPrompt
    except Exception:
        _build_prompt = agent_tools.buildSystemPrompt
    if max_iters is None:
        try:
            max_iters = int(config.agent_max_iters)
        except Exception:
            max_iters = 3
    try:
        max_iters = int(max_iters)
    except Exception:
        max_iters = 3
    if max_iters < 1:
        max_iters = 1
    if max_iters > 5:
        max_iters = 5
    history = history or []
    if not config.cfgEndpoint:
        return "ERROR: agent endpoint not configured. Open /agent."
    req = {"model": config.cfgModel, "temperature": 0.7, "max_tokens": 800,
           "stream": False, "messages": []}
    msgs = req["messages"]
    msgs.append({"role": "system", "content": _build_prompt()})
    # The browser sends its live transcript; the device log is the fallback
    # for a fresh page (refresh / another browser) so context survives.
    if not history:
        agent_tools.injectRecentLog(msgs, userMsg, 8, path=log_path)
    addHistoryCapped(msgs, history, 8)
    msgs.append({"role": "user", "content": userMsg[:1500]})
    agent_tools.addToolsArray(req)

    toolsLog = ""
    toolSummary = ""
    pendingPrefix = ""
    finalText = ""
    finalReason = ""
    sawHttpFail = False
    for it in range(max_iters):
        try:
            body = json.dumps(req)
        except Exception as e:
            return "ERROR: json encode: %s" % str(e)[:120]
        print("[agent] iter%d body=%dB msgs=%d" % (it, len(body), len(msgs)))
        ok, resp, code = postLLM(body)
        if not ok:
            if it > 0 and toolSummary:
                sawHttpFail = True
                break
            return "ERROR: upstream request failed: %s" % resp[:200]
        if code < 200 or code >= 300:
            if len(resp) > 600:
                resp = resp[:600]
            if it > 0 and toolSummary:
                print("[agent] follow-up HTTP %d, answering from tool results" % code)
                sawHttpFail = True
                break
            return "ERROR: upstream HTTP %d: %s" % (code, resp)
        try:
            res = json.loads(resp)
        except Exception:
            if it > 0 and toolSummary:
                sawHttpFail = True
                break
            return "ERROR: bad JSON from endpoint."
        try:
            msg0 = res["choices"][0]["message"]
        except Exception:
            return "ERROR: empty reply from model."
        calls = msg0.get("tool_calls")
        legacy = msg0.get("function_call")
        hasLegacy = isinstance(legacy, dict) and bool(legacy.get("name"))
        if not calls and not hasLegacy:
            c1 = msg0.get("content", "") or ""
            rCC = msg0.get("reasoning_content", "") or ""
            rR = msg0.get("reasoning", "") or ""
            rD = ""
            try:
                det = msg0.get("reasoning_details")
                if isinstance(det, list) and det:
                    rD = det[0].get("text", "") or ""
            except Exception:
                pass
            if c1:
                finalText = c1
            elif rCC:
                finalText = rCC
            elif rR:
                finalText = rR
            elif rD:
                finalText = rD
            else:
                print("[agent] no content: %s" % resp[:300])
                finalText = ""
            if rCC:
                finalReason += rCC
            elif rR:
                finalReason += rR
            elif rD:
                finalReason += rD
            if pendingPrefix and finalText:
                finalText = pendingPrefix + finalText
            break
        # collect calls (cap 20)
        call_list = []
        if isinstance(calls, list):
            for tc in calls:
                if len(call_list) >= 20:
                    break
                if not isinstance(tc, dict):
                    continue
                cid = tc.get("id", "") or "call_%d_%d" % (it, len(call_list))
                fn = tc.get("function", {}) or {}
                nm = fn.get("name", "") or ""
                ag = fn.get("arguments", "") or ""
                if not nm:
                    continue
                call_list.append((cid, nm, ag))
        if hasLegacy and len(call_list) < 20:
            nm = legacy.get("name", "") or ""
            ag = legacy.get("arguments", "") or ""
            if nm:
                call_list.append(("call_%d_0" % it, nm, ag))
        if not call_list:
            finalText = msg0.get("content", "") or ""
            break
        pre = msg0.get("content", "") or ""
        preR = msg0.get("reasoning_content", "") or msg0.get("reasoning", "") or ""
        if pre:
            pendingPrefix += pre[:500] + "\n"
            if len(pendingPrefix) > 800:
                pendingPrefix = pendingPrefix[:800]
        if preR:
            finalReason += preR[:800] + "\n"
            if len(finalReason) > 3000:
                finalReason = finalReason[:3000]
        am = {"role": "assistant"}
        if pre:
            am["content"] = pre[:500]
        am["tool_calls"] = [{"id": cid, "type": "function",
                             "function": {"name": nm, "arguments": ag}}
                            for (cid, nm, ag) in call_list]
        msgs.append(am)
        import time
        t0 = time.ticks_ms() if hasattr(time, "ticks_ms") else 0

        def _elapsed():
            try:
                return time.ticks_diff(time.ticks_ms(), t0)
            except Exception:
                return 0
        for idx2, (cid, nm, ag) in enumerate(call_list):
            if not agent_tools.toolEnabled(nm):
                msgs.append({"role": "tool", "tool_call_id": cid,
                             "content": '{"error":"tool disabled in /functions"}'})
                toolsLog += nm + "(disabled) "
                toolSummary += nm + ": disabled\n"
                continue
            if idx2 > 0 and _elapsed() > 25000:
                res2 = '{"error":"tool time budget (25s) exceeded, skipped"}'
                print("[tool] %s SKIPPED (budget)" % nm)
            else:
                try:
                    ad = json.loads(ag) if ag else {}
                    if not isinstance(ad, dict):
                        ad = {}
                except Exception:
                    ad = {}
                res2 = agent_tools.execTool(nm, ad)
                print("[tool] %s -> %s" % (nm, res2[:120]))
            msgs.append({"role": "tool", "tool_call_id": cid, "content": res2, "name": nm})
            toolsLog += nm + " "
            toolSummary += "%s: %s\n" % (nm, res2[:400])
            if len(toolSummary) > 1500:
                toolSummary = toolSummary[:1500]
    if not finalText and toolSummary:
        if sawHttpFail:
            finalText = "Ran " + toolsLog + "but the summary request failed. Results:\n" + toolSummary
        else:
            finalText = "Ran " + toolsLog + "(step budget reached before a summary). Results:\n" + toolSummary
    if not finalText:
        finalText = "(tool run done, no text reply)"
    if len(finalText) > 3500:
        finalText = finalText[:3500]
    if out is not None:
        out["reasoning"] = (finalReason or "")[:2500]
        out["tools_used"] = toolsLog
    agent_tools.appendChatLog(userMsg, finalText, path=log_path)
    if agent_tools.gRestartPending:
        pass  # caller reboots after response
    return finalText


def callLLM(userMsg, history=None, outReasoning=None):
    """Legacy plain (non-tool) path, kept for reference/debug."""
    import config
    import agent_tools
    try:
        import prompt as _promptmod
        _build_prompt = _promptmod.buildMiniPrompt
    except Exception:
        _build_prompt = agent_tools.buildSystemPrompt
    history = history or []
    if not config.cfgEndpoint:
        return "ERROR: agent endpoint not configured. Open /agent."
    req = {"model": config.cfgModel, "temperature": 0.7, "max_tokens": 800,
           "stream": False, "messages": []}
    msgs = req["messages"]
    msgs.append({"role": "system", "content": _build_prompt()})
    if not history:
        agent_tools.injectRecentLog(msgs, userMsg, 8)
    for m in (history or [])[:16]:
        if not isinstance(m, dict):
            continue
        r, c = m.get("role", ""), m.get("content", "")
        if r not in ("user", "assistant", "system") or not c:
            continue
        msgs.append({"role": r, "content": str(c)[:1500]})
    msgs.append({"role": "user", "content": userMsg[:1500]})
    try:
        body = json.dumps(req)
    except Exception as e:
        return "ERROR: json encode: %s" % str(e)[:100]
    ok, resp, code = postLLM(body)
    if not ok:
        return "ERROR: upstream request failed: %s" % resp[:120]
    if code < 200 or code >= 300:
        return "ERROR: upstream HTTP %d: %s" % (code, resp[:800])
    try:
        res = json.loads(resp)
    except Exception as e:
        return "ERROR: bad JSON from endpoint: %s" % str(e)[:100]
    try:
        m0 = res["choices"][0]["message"]
    except Exception:
        return "ERROR: empty reply from model."
    content = m0.get("content") or m0.get("text") or m0.get("reasoning_content") \
        or m0.get("reasoning") or ""
    try:
        det = m0.get("reasoning_details")
        if not content and isinstance(det, list) and det:
            content = det[0].get("text", "") or ""
    except Exception:
        pass
    errMsg = ""
    try:
        errMsg = res.get("error", {}).get("message", "") or ""
    except Exception:
        pass
    if not content:
        if errMsg:
            return "ERROR: " + errMsg
        return "ERROR: empty reply from model."
    return content[:4000]
