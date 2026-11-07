"""Console view: header button + drawer on every page, /api/logs backend."""
import os
import re

PROJ = os.path.join(os.path.dirname(__file__), "..")
WWW = os.path.join(PROJ, "www")
PAGES = ("agent.html", "chat.html", "docs.html", "files.html",
         "functions.html", "setup.html", "update.html", "wifi.html")

NATIVE_DIALOG = re.compile(r"\b(alert|confirm|prompt)\s*\(")


def _read(name):
    with open(os.path.join(WWW, name), encoding="utf-8") as f:
        return f.read()


def test_all_pages_have_console_button_and_drawer():
    for name in PAGES:
        src = _read(name)
        assert 'id="consolebtn"' in src, "%s: missing header button" % name
        assert 'id="consoledrawer"' in src, "%s: missing drawer" % name
        assert 'id="cslpre"' in src, "%s: missing log <pre>" % name
        assert 'id="cslstatus"' in src, "%s: missing status line" % name
        # button lives in the header next to the theme toggle
        assert src.index('id="consolebtn"') < src.index('id="consoledrawer"'), name


def test_console_fetches_logs_and_status_with_auth():
    for name in PAGES:
        src = _read(name)
        assert "/api/logs" in src, "%s: drawer never calls /api/logs" % name
        assert "/api/status" in src, "%s: drawer never shows status" % name
        assert "esp32_token" in src, "%s: drawer sends no auth token" % name


def test_console_has_reload_pause_copy_clear_close():
    for name in PAGES:
        src = _read(name)
        for bid in ("cslrefresh", "cslpause", "cslcopy", "cslclear", "cslclose"):
            assert 'id="%s"' % bid in src, "%s: missing #%s" % (name, bid)


def test_console_drawer_is_resizable():
    for name in PAGES:
        src = _read(name)
        assert 'id="cslgrab"' in src, "%s: missing drag handle" % name
        assert "pointerdown" in src, "%s: no drag start" % name
        assert "setPointerCapture" in src, "%s: drag loses pointer" % name
        assert "csl_height" in src, "%s: height not persisted" % name
        assert "touch-action:none" in src.replace(" ", ""), \
            "%s: touch drag would scroll the page" % name


def test_console_drawer_has_no_upward_fade():
    import re
    for name in PAGES:
        src = _read(name)
        m = re.search(r"#consoledrawer\{[^}]*\}", src)
        assert m, "%s: drawer rule missing" % name
        assert "box-shadow" not in m.group(0), \
            "%s: drawer shadow fades over the page" % name


def test_no_native_dialogs_app_wide():
    bad = []
    for name in PAGES:
        src = _read(name)
        for m in NATIVE_DIALOG.finditer(src):
            bad.append("%s: native %s" % (name, m.group(0)))
    assert not bad, "native dialogs banned app-wide:\n" + "\n".join(bad)


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
