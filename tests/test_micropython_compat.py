"""Regression tests for MicroPython portability landmines in llm.py.

These encode bugs that only appear ON the device, so they are cheap here and
expensive to rediscover on the bench.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import llm


def test_no_unsupported_codecs_in_source():
    """MicroPython ships only utf-8/ascii codecs.

    `shead.decode("iso-8859-1", "ignore")` raised
    "unknown encoding: iso-8859-1" on-device for EVERY successful response.
    The TLS layer was failing first, so the bug stayed hidden until the
    firmware was fixed. Guard the source against re-introduction.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..", "llm.py"),
               encoding="utf-8").read()
    # Ignore comments: the fix documents the codec by name.
    code_lines = [ln for ln in src.splitlines()
                  if not ln.lstrip().startswith("#")]
    body = "\n".join(code_lines)
    for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
        assert codec not in body, "unsupported MicroPython codec: %s" % codec


def test_content_length_parsed_from_bytes():
    """Header parsing must work on bytes (no decode) — see comment above."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "llm.py"),
               encoding="utf-8").read()
    assert 'b"content-length:"' in src.lower()
