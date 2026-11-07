"""web_fetch: URL/redirect handling now mirrors the C++ HTTPClient.

The C++ tool had a 15 s timeout and followed redirects. The MicroPython port
used bare `urequests`, which does neither — so http->https and `/moved`
links failed. These tests cover the replacement raw-socket helper.
"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import stubs

stubs.install()

from tools import tool_web_fetch as wf


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.path == "/final":
            body = b"<html><head><style>x{}</style></head><body><h1>Hello</h1><script>bad()</script> world</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/boom":
            body = b"nope"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def test_split_url_and_origin():
    assert wf._split_url("https://api.test/v1/x") == (True, "api.test", 443, "/v1/x")
    assert wf._split_url("http://host:8080/a") == (False, "host", 8080, "/a")
    assert wf._split_url("http://host") == (False, "host", 80, "/")
    assert wf._origin("https://host/v1/x") == "https://host"
    assert wf._origin("http://host:8080/v1") == "http://host:8080"


def test_resolve_redirect():
    base = "https://example.com/a/b/page.html"
    assert wf._resolve_redirect(base, "/c") == "https://example.com/c"
    assert wf._resolve_redirect(base, "next") == "https://example.com/a/b/next"
    assert wf._resolve_redirect(base, "//cdn.test/x") == "https://cdn.test/x"
    assert wf._resolve_redirect(base, "http://other.test/y") == "http://other.test/y"


def test_fetch_follows_redirect_and_strips_html():
    srv = _serve()
    try:
        port = srv.server_address[1]
        text, err = wf._fetch("http://127.0.0.1:%d/start" % port)
        assert err == ""
        assert "Hello" in text and "world" in text
        assert "bad()" not in text and "x{}" not in text
    finally:
        srv.shutdown()


def test_fetch_reports_http_error():
    srv = _serve()
    try:
        port = srv.server_address[1]
        text, err = wf._fetch("http://127.0.0.1:%d/boom" % port)
        assert text is None
        assert "HTTP 404" in err
    finally:
        srv.shutdown()


def test_strip_html_entities_and_whitespace():
    out = wf._strip_html("<p>a &amp; b</p>\n\n<p>c</p>")
    assert out == "a & b c"


def test_dechunk_handles_partial_and_extensions():
    body = b"5\r\nhello\r\n6;ext=1\r\n world\r\n0\r\n\r\n"
    assert wf._dechunk(body) == b"hello world"
    # truncated mid-chunk: keep what arrived
    assert wf._dechunk(b"5\r\nhel") == b"hel"
