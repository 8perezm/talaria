# tool_web_fetch — GET a URL, return cleaned text (<=2000 chars).
try:
    import ujson as json
except ImportError:
    import json


def _strip_html(html, max_chars=2000):
    t = html
    # remove script/style blocks (case-insensitive scan)
    try:
        low = t.lower()
        for tag in ("script", "style"):
            op = "<" + tag
            cl = "</" + tag
            while True:
                s = low.find(op)
                if s < 0:
                    break
                ce = low.find(cl, s + len(op))
                if ce < 0:
                    t = t[:s]
                    low = low[:s]
                    break
                ge = low.find(">", ce + len(cl))
                if ge < 0:
                    ge = len(t) - 1
                t = t[:s] + t[ge + 1:]
                low = low[:s] + low[ge + 1:]
    except Exception:
        pass
    # strip tags
    out_chars = []
    in_tag = False
    for c in t:
        if not in_tag and c == "<":
            in_tag = True
            continue
        if in_tag:
            if c == ">":
                in_tag = False
                out_chars.append(" ")
            continue
        out_chars.append(c)
    no_tag = "".join(out_chars)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&#x27;", "'")):
        no_tag = no_tag.replace(a, b)
    # collapse whitespace
    collapsed = []
    last_space = True
    for c in no_tag:
        sp = c in (" ", "\t", "\r", "\n", "\f", "\v")
        if sp:
            if not last_space:
                collapsed.append(" ")
                last_space = True
        else:
            collapsed.append(c)
            last_space = False
        if len(collapsed) >= max_chars + 32:
            break
    s = "".join(collapsed).strip()
    if len(s) > max_chars:
        s = s[:max_chars]
    return s


_MAX_BODY = 8000
_TIMEOUT = 15          # per socket op, mirrors the C++ 15 s HTTPClient timeout
_TOTAL_BUDGET_MS = 20000
_MAX_REDIRECTS = 3


def _split_url(url):
    """(is_https, host, port, path) — same normalisation as llm/server."""
    u = (url or "").strip()
    if u.startswith("https://"):
        is_https, rest = True, u[8:]
    elif u.startswith("http://"):
        is_https, rest = False, u[7:]
    else:
        is_https, rest = False, u
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


def _origin(url):
    is_https, host, port, _path = _split_url(url)
    scheme = "https" if is_https else "http"
    default = 443 if is_https else 80
    if port == default:
        return scheme + "://" + host
    return scheme + "://" + host + ":" + str(port)


def _resolve_redirect(base, loc):
    """Turn a Location header into an absolute URL (http(s), //, /, relative)."""
    loc = (loc or "").strip()
    if loc.startswith("http://") or loc.startswith("https://"):
        return loc
    if loc.startswith("//"):
        return ("https:" if base.startswith("https://") else "http:") + loc
    if loc.startswith("/"):
        return _origin(base) + loc
    _is_https, _h, _p, path = _split_url(base)
    slash = path.rfind("/")
    return _origin(base) + (path[:slash + 1] if slash >= 0 else "/") + loc


def _dechunk(data):
    """Decode a Transfer-Encoding: chunked body (partial data is fine)."""
    out = b""
    pos = 0
    while pos < len(data) and len(out) < _MAX_BODY:
        nl = data.find(b"\r\n", pos)
        if nl < 0:
            break
        line = data[pos:nl].split(b";")[0].strip()
        try:
            size = int(line, 16)
        except Exception:
            break
        if size <= 0:
            break
        start = nl + 2
        out += data[start:start + size]
        pos = start + size + 2
    return out[:_MAX_BODY]


def _http_get(url):
    """One GET over a raw socket. Returns (status, headers, body_bytes)."""
    import socket
    import time

    is_https, host, port, path = _split_url(url)
    t0 = time.ticks_ms() if hasattr(time, "ticks_ms") else 0

    def _expired():
        try:
            return time.ticks_diff(time.ticks_ms(), t0) > _TOTAL_BUDGET_MS
        except Exception:
            return False

    addrs = [i[4] for i in socket.getaddrinfo(host, port) if i[0] == socket.AF_INET]
    if not addrs:
        raise OSError("no address for %s" % host)
    s = socket.socket()
    try:
        s.settimeout(_TIMEOUT)
        s.connect(addrs[0])
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
                    s = _wrap(s)  # very old ussl without SNI
            else:
                _ctx = _sslmod.create_default_context()
                _ctx.check_hostname = False
                _ctx.verify_mode = _sslmod.CERT_NONE
                s = _ctx.wrap_socket(s, server_hostname=host)
            # MicroPython's SSLSocket has no settimeout(); the timeout set on
            # the plain socket before wrapping stays in effect.
            try:
                s.settimeout(_TIMEOUT)
            except Exception:
                pass
        req = ("GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: Talaria-Agent/1.0\r\n"
               "Accept: text/html,text/plain,*/*\r\nConnection: close\r\n\r\n"
               % (path, host)).encode()
        sent = 0
        while sent < len(req):
            n = s.send(req[sent:])
            if n is None:
                continue
            if n <= 0:
                raise OSError("send stalled")
            sent += n

        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192 and not _expired():
            d = s.recv(512)
            if not d:
                break
            buf += d
        if b"\r\n\r\n" not in buf:
            raise OSError("bad headers")
        head, body = buf.split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n")
        try:
            status = int(lines[0].split(b" ")[1])
        except Exception:
            raise OSError("bad status")
        headers = {}
        for ln in lines[1:]:
            p = ln.find(b":")
            if p > 0:
                headers[ln[:p].strip().lower()] = ln[p + 1:].strip()
        while len(body) < _MAX_BODY and not _expired():
            d = s.recv(1024)
            if not d:
                break
            body += d
        return status, headers, body[:_MAX_BODY]
    finally:
        try:
            s.close()
        except Exception:
            pass


def _fetch(url):
    # returns (text, err); follows up to 3 redirects like the C++ HTTPClient
    cur = url
    for _hop in range(_MAX_REDIRECTS + 1):
        try:
            status, headers, body = _http_get(cur)
        except Exception as e:
            return None, "request failed: %s" % str(e)[:120]
        if status in (301, 302, 303, 307, 308):
            loc = headers.get(b"location") or headers.get(b"Location") or b""
            if isinstance(loc, bytes):
                loc = loc.decode("utf-8", "ignore")
            if not loc:
                return None, "HTTP %d without Location" % status
            cur = _resolve_redirect(cur, loc)
            continue
        if b"chunked" in headers.get(b"transfer-encoding", b"").lower():
            body = _dechunk(body)
        if status < 200 or status >= 300:
            eb = body[:300].decode("utf-8", "ignore").replace('"', "'").replace("\n", " ")
            return None, "HTTP %s: %s" % (status, eb)
        if not body:
            return None, "empty body"
        text = _strip_html(body.decode("utf-8", "ignore"), 2000)
        if not text:
            return None, "no text extracted"
        return text, ""
    return None, "too many redirects"


def fetch_raw(url):
    """GET a URL for on-device scripts: return the body bytes.

    Follows redirects, decodes chunked bodies and raises OSError on HTTP
    errors. The model-facing tool strips HTML to text; a script usually wants
    the JSON body instead:

        from tools.tool_web_fetch import fetch_raw
        body = fetch_raw("https://api.open-meteo.com/v1/forecast?...")
        data = json.loads(body.decode())
    """
    cur = str(url or "").strip()
    for _hop in range(_MAX_REDIRECTS + 1):
        status, headers, body = _http_get(cur)
        if status in (301, 302, 303, 307, 308):
            loc = headers.get(b"location") or headers.get(b"Location") or b""
            if isinstance(loc, bytes):
                loc = loc.decode("utf-8", "ignore")
            if not loc:
                raise OSError("HTTP %d without Location" % status)
            cur = _resolve_redirect(cur, loc)
            continue
        if b"chunked" in headers.get(b"transfer-encoding", b"").lower():
            body = _dechunk(body)
        if status < 200 or status >= 300:
            raise OSError("HTTP %d" % status)
        return body[:_MAX_BODY]
    raise OSError("too many redirects")


def _run(args):
    out = {}
    url = str(args.get("url", "") if isinstance(args, dict) else "").strip()
    if not url:
        out["error"] = "url required (include https://)"
    elif len(url) > 512:
        out["error"] = "url too long (max 512)"
    elif not (url.startswith("http://") or url.startswith("https://")):
        out["error"] = "url must start with http:// or https://"
    else:
        txt, err = _fetch(url)
        if txt is not None:
            out["url"] = url[:200]
            out["text"] = txt
        else:
            out["error"] = (err or "fetch failed")[:300]
            out["url"] = url[:200]
    return json.dumps(out)


TOOL = {
    "name": "web_fetch",
    "ui_hint": "Fetch a web page as text",
    "description": "Fetch an http(s) URL and return its text (up to ~2000 chars). Use for current info, docs, prices, headlines. No JS, no login pages.",
    "parameters": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    "run": _run,
    "max_result_chars": 2200,
}
