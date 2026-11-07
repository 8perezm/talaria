"""MicroPython's % formatting is stricter than CPython's.

CPython silently accepts C-style length modifiers like %lu; MicroPython
raises "unsupported format character" at runtime (this exact bug 500'd every
chat call on-device while all host tests stayed green). Scan every shipped
.py file for % codes outside MicroPython's supported set.
"""
import os
import re

ALLOWED = set("sdioxXeEfFgGcra%")  # MicroPython-supported conversions
# NOTE: %u and length modifiers (%l, %h) are deliberately ABSENT — use %d.

PROJ = os.path.join(os.path.dirname(__file__), "..")


def _py_files():
    for root, dirs, files in os.walk(PROJ):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        if "tests" in root.split(os.sep):
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def test_no_unsupported_percent_formats():
    # matches % [flags/width/prec/length]* conversion, incl. %% (allowed)
    pat = re.compile(r"%[#0\- +]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[hlL]?([a-zA-Z%])")
    bad = []
    for path in _py_files():
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                code = line.split("#", 1)[0]  # ignore comments
                for m in pat.finditer(code):
                    if m.group(1) not in ALLOWED:
                        bad.append("%s:%d: %%%s (%s)" % (
                            os.path.relpath(path, PROJ), n, m.group(1),
                            line.strip()[:90]))
    assert not bad, "unsupported %-formats for MicroPython:\n" + "\n".join(bad)
