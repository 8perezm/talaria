"""Tests for the SSE streaming path: chunked decoding + event splitting."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import llm


class FakeSock:
    """Feeds a fixed byte string in small pieces, like a real recv()."""

    def __init__(self, data, step=7):
        self.data = data
        self.pos = 0
        self.step = step

    def recv(self, n):
        n = min(n, self.step)
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk


def _drain(reader):
    out = b""
    for _ in range(500):
        d = reader.read(64)
        if not d:
            break
        out += d
    return out


def test_chunked_reader_basic():
    body = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
    r = llm._ChunkedReader(FakeSock(body, step=3), b"")
    assert _drain(r) == b"hello world"


def test_chunked_reader_with_initial_buffer():
    # the header split leaves some body already buffered
    buffered = b"5\r\nhel"
    rest = b"lo\r\n0\r\n\r\n"
    r = llm._ChunkedReader(FakeSock(rest, step=2), buffered)
    assert _drain(r) == b"hello"


def test_chunked_reader_hex_sizes_and_extensions():
    body = b"A\r\n0123456789\r\n2;ext=1\r\nok\r\n0\r\n\r\n"
    r = llm._ChunkedReader(FakeSock(body, step=4), b"")
    assert _drain(r) == b"0123456789ok"


def test_chunked_reader_byte_at_a_time():
    body = b"3\r\nabc\r\n0\r\n\r\n"
    r = llm._ChunkedReader(FakeSock(body, step=1), b"")
    assert _drain(r) == b"abc"


def test_chunked_reader_non_ascii_payload():
    payload = "café ☕".encode("utf-8")
    body = ("%X\r\n" % len(payload)).encode() + payload + b"\r\n0\r\n\r\n"
    r = llm._ChunkedReader(FakeSock(body, step=5), b"")
    assert _drain(r).decode("utf-8") == "café ☕"
