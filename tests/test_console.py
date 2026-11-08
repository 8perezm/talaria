"""Console view: /api/logs backend + logbuf wiring.

The drawer UI itself is part of the React SPA and is pinned by test_spa.py;
these cases keep the device-side log buffer honest.
"""
import os

PROJ = os.path.join(os.path.dirname(__file__), "..")




def test_logs_endpoints_registered():
    with open(os.path.join(PROJ, "server.py"), encoding="utf-8") as f:
        src = f.read()
    assert '"/api/logs"' in src
    assert '"/api/logs/clear"' in src
    assert "logbuf.get" in src
    assert "logbuf.clear" in src


def test_main_installs_logbuf_before_first_print():
    with open(os.path.join(PROJ, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "logbuf.install()" in src
    assert src.index("logbuf.install()") < src.index("Agent boot")


def test_logbuf_source_is_micropython_safe():
    with open(os.path.join(PROJ, "logbuf.py", ), encoding="utf-8") as f:
        src = f.read()
    code = "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("#"))
    for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
        assert codec not in code
    assert "f\"" not in code and "f'" not in code, "use % formatting (see test_printf_compat)"
