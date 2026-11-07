import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import server


class _Req:
    def __init__(self, body, ctype):
        self.body = body
        self.headers = {"Content-Type": ctype}


def test_parse_multipart_single_file():
    boundary = "----MicrodotBoundary1234"
    body = (
        "--" + boundary + "\r\n"
        'Content-Disposition: form-data; name="firmware"; filename="main.py"\r\n'
        "Content-Type: text/x-python\r\n\r\n"
        "print('hello')\n"
        "\r\n--" + boundary + "--\r\n"
    ).encode()
    req = _Req(body, "multipart/form-data; boundary=" + boundary)
    files = server._parse_multipart(req)
    assert "firmware" in files
    assert files["firmware"].read() == b"print('hello')\n"


def test_parse_multipart_non_multipart():
    req = _Req(b"{}", "application/json")
    assert server._parse_multipart(req) == {}
