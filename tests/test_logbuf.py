"""Tests for logbuf.py — the /api/logs ring buffer behind the console view."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import logbuf


def _reset():
    logbuf.clear()
    logbuf._SEQ = 0
    logbuf._OPEN = False
    try:
        del logbuf._BUF[:]
    except Exception:
        pass


def test_push_get_roundtrip():
    _reset()
    s1 = logbuf.push("hello")
    s2 = logbuf.push("[agent] iter1")
    assert s2 > s1 > 0
    entries, seq = logbuf.get(0)
    assert seq == s2
    assert [e["msg"] for e in entries] == ["hello", "[agent] iter1"]
    assert [e["seq"] for e in entries] == [s1, s2]


def test_multiline_push_splits():
    _reset()
    logbuf.push("a\nb\n")
    entries, _ = logbuf.get(0)
    assert [e["msg"] for e in entries] == ["a", "b"]


def test_long_lines_truncated():
    _reset()
    logbuf.push("x" * (logbuf.MAX_LINE + 50))
    entries, _ = logbuf.get(0)
    assert len(entries) == 1
    assert len(entries[0]["msg"]) == logbuf.MAX_LINE


def test_buffer_capped():
    _reset()
    for i in range(logbuf.MAX_LINES + 50):
        logbuf.push("line %d" % i)
    assert logbuf.count() == logbuf.MAX_LINES
    entries, _ = logbuf.get(0, limit=300)
    assert len(entries) == logbuf.MAX_LINES
    assert entries[0]["msg"] == "line 50"


def test_since_and_limit():
    _reset()
    for i in range(10):
        logbuf.push("m%d" % i)
    entries, seq = logbuf.get(0)
    mid = entries[4]["seq"]
    tail, seq2 = logbuf.get(mid)
    assert seq2 == seq
    assert [e["msg"] for e in tail] == ["m%d" % i for i in range(5, 10)]
    few, _ = logbuf.get(0, limit=3)
    assert [e["msg"] for e in few] == ["m7", "m8", "m9"]
    # clamps, never raises
    logbuf.get("bogus", "bogus")
    big, _ = logbuf.get(0, limit=99999)
    assert len(big) == 10


def test_clear_keeps_seq_monotonic():
    _reset()
    a = logbuf.push("before")
    logbuf.clear()
    entries, seq = logbuf.get(0)
    assert entries == []
    assert logbuf.count() == 0
    b = logbuf.push("after")
    assert b > a and seq >= a
    entries, _ = logbuf.get(a)
    assert [e["msg"] for e in entries] == ["after"]


def test_push_continue_appends_to_last_line():
    _reset()
    logbuf.push("WiFi")
    logbuf.push_continue(".")
    logbuf.push_continue(".")
    entries, _ = logbuf.get(0)
    assert [e["msg"] for e in entries] == ["WiFi.."]


def test_install_captures_print_and_is_idempotent():
    import builtins
    _reset()
    orig = builtins.print
    try:
        assert logbuf.install() is True
        assert logbuf.install() is True  # second call is a no-op
        print("captured line")
        print("dots", end="")
        print("more", end="")
        print("real line")
        entries, _ = logbuf.get(0)
        msgs = [e["msg"] for e in entries]
        assert "captured line" in msgs
        # unterminated fragments share one terminal line, closed by the
        # next newline print — mirrors what serial actually shows
        assert "dotsmorereal line" in msgs
    finally:
        builtins.print = orig
        logbuf._installed = False
        logbuf._orig_print = None


def test_push_never_raises():
    _reset()
    logbuf.push(None)
    logbuf.push(b"\xff\xfe bytes")
    logbuf.push(object())
    entries, _ = logbuf.get(0)
    assert len(entries) == 3
