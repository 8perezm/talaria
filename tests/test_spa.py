# test_spa.py — the React dashboard contract.
#
# The UI is a compiled SPA (ui/ -> www/): index.html + assets/app.js +
# assets/app.css. There are no per-route HTML files any more, so the old
# "page route registered / page file exists / nav href resolves" assertions
# are replaced here by the equivalent guarantees for a single-page app:
#
#   * the shell is served for every client route,
#   * the server never serves a device file outside the web root,
#   * /api routes are not swallowed by the SPA fallback,
#   * the sidebar nav and the client router stay in sync,
#   * the bundle stays inside its flash budget.
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import server  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), "..")
WWW = os.path.join(BASE, "www")
UI = os.path.join(BASE, "ui", "src")

ROUTES = [
    "/",
    "/sessions",
    "/files",
    "/analytics",
    "/models",
    "/logs",
    "/cron",
    "/skills",
    "/tools",
    "/channels",
    "/config",
    "/keys",
    "/login",
    "/system",
    "/docs",
    "/setup",
    "/wifi",
    "/update",
]

BUNDLE_BUDGET = 900 * 1024  # js + css; ~13 MB of flash is free post-dashboard


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _header(res, name):
    headers = dict(getattr(res, "headers", {}) or {})
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _get(path, headers=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        return await client.get(path, headers=headers or {})

    return asyncio.run(_do())


# ---- 1. the web root holds only the compiled bundle --------------------

def test_www_has_no_legacy_pages():
    names = sorted(os.listdir(WWW))
    html = [n for n in names if n.endswith(".html")]
    assert html == ["index.html"], html
    # No stray hand-written CSS/JS/sprite from the pre-React UI.
    assert "dash.css" not in names
    assert "icons.svg" not in names
    assert os.path.isdir(os.path.join(WWW, "assets")), names


def test_bundle_files_present_and_within_budget():
    js = os.path.join(WWW, "assets", "app.js")
    css = os.path.join(WWW, "assets", "app.css")
    for path in (js, css, os.path.join(WWW, "index.html")):
        assert os.path.exists(path), path
        assert os.stat(path)[6] > 0, path
    total = os.stat(js)[6] + os.stat(css)[6]
    assert total < BUNDLE_BUDGET, "bundle %d bytes exceeds budget" % total


def test_index_references_the_bundle():
    html = _read(os.path.join(WWW, "index.html"))
    assert 'id="root"' in html
    assert re.search(r'src="/assets/app\.js(\?v=[0-9a-f]+)?"', html), html[:400]
    assert re.search(r'href="/assets/app\.css(\?v=[0-9a-f]+)?"', html), html[:400]
    # Cache-busting stamp: without it a returning browser keeps a stale bundle
    # and the device never gets to serve the new one.
    assert re.search(r"app\.js\?v=[0-9a-f]{6,}", html), html[:400]


# ---- 2. every client route is served the shell -------------------------

def test_shell_served_for_every_route(tmp_path, monkeypatch):
    monkeypatch.chdir(BASE)
    for path in ROUTES:
        res = _get(path)
        assert res.status_code == 200, (path, res.status_code)
        assert "text/html" in _header(res, "Content-Type"), (path, res.status_code)
        assert 'id="root"' in res.text, path


def test_unknown_route_falls_back_to_shell(tmp_path, monkeypatch):
    monkeypatch.chdir(BASE)
    res = _get("/no-such-route/deep/link")
    assert res.status_code == 200
    assert 'id="root"' in res.text
    assert "no-cache" in _header(res, "Cache-Control").lower()


def test_assets_get_long_lived_cache_and_mime(tmp_path, monkeypatch):
    monkeypatch.chdir(BASE)
    js = _get("/assets/app.js")
    assert js.status_code == 200
    assert "javascript" in _header(js, "Content-Type")
    assert "immutable" in _header(js, "Cache-Control")

    css = _get("/assets/app.css")
    assert css.status_code == 200
    assert "text/css" in _header(css, "Content-Type")

    icon = _get("/favicon.svg")
    assert icon.status_code == 200
    assert "svg" in _header(icon, "Content-Type")


def test_gzip_twin_is_preferred_when_accepted(tmp_path, monkeypatch):
    """The device cannot compress at request time; the build ships .gz twins."""
    monkeypatch.chdir(BASE)
    assert os.path.exists(os.path.join(WWW, "assets", "app.js.gz"))
    assert os.path.exists(os.path.join(WWW, "assets", "app.css.gz"))

    gz = _get("/assets/app.js", headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200
    assert "gzip" in _header(gz, "Content-Encoding")
    assert "Accept-Encoding" in _header(gz, "Vary")

    plain = _get("/assets/app.js", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200
    assert _header(plain, "Content-Encoding") in ("", None)


# ---- 3. the web root cannot be walked out of --------------------------

def test_static_handler_refuses_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(BASE)
    for path in ("/assets/../config.py",
                 "/assets/%2e%2e/config.py",
                 "/../config.json",
                 "/assets/../../server.py"):
        res = _get(path)
        # Either the router 404s it or the shell answers — never a device file.
        body = res.text or ""
        assert "cfgApiKey" not in body, path
        assert "class Microdot" not in body, path
        assert "AP_SSID" not in body, path


def test_api_not_swallowed_by_spa_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(BASE)
    res = _get("/api/status")
    # A configured auth token from another test may 401 this — either way the
    # request must reach the API, not the SPA shell.
    assert res.status_code in (200, 401), res.status_code
    body = res.text or ""
    assert 'id="root"' not in body
    if res.status_code == 200:
        assert res.json.get("fs_ok") in (True, False), body[:200]

    missing = _get("/api/definitely-not-a-route")
    assert missing.status_code == 404
    assert 'id="root"' not in (missing.text or "")


# ---- 4. nav <-> router parity -----------------------------------------

def _nav_paths():
    src = _read(os.path.join(UI, "components", "Shell.tsx"))
    block = src.split("export const NAV", 1)[1]
    block = block.split("= [", 1)[1].split("\n]", 1)[0]
    return re.findall(r"path:\s*'([^']+)'", block)


def _router_paths():
    src = _read(os.path.join(UI, "App.tsx"))
    return re.findall(r'<Route path="([^"]+)"', src)


def test_nav_and_router_agree():
    nav = _nav_paths()
    routes = set(_router_paths())
    assert nav, "no NAV entries found"
    for path in nav:
        assert path in routes, "nav entry %s has no Route" % path
    # Every route that is user-facing must be reachable from the sidebar…
    redirects = {"/agent", "/functions", "/stats", "/journey", "/admin", "*"}
    # …except the onboarding/plumbing screens, which are linked from the pages
    # that own them (Config, System, the AP captive portal) rather than the nav.
    # /login is the full-screen auth gate, not a sidebar destination.
    utilities = {"/setup", "/wifi", "/update", "/login"}
    for path in _router_paths():
        if path in redirects or path in utilities:
            continue
        assert path in nav, "route %s is missing from the sidebar" % path


def test_nav_matches_upstream_shape():
    nav = _nav_paths()
    # The upstream dashboard's ordering and labels, adapted to this device.
    assert nav[:4] == ["/", "/sessions", "/files", "/analytics"], nav
    for expected in ("/models", "/logs", "/cron", "/skills", "/tools",
                     "/channels", "/config", "/keys", "/system", "/docs"):
        assert expected in nav, expected


# ---- 5. house rules for the React sources -----------------------------

def _ui_sources():
    for root, _dirs, files in os.walk(UI):
        for name in files:
            if name.endswith((".ts", ".tsx", ".css")):
                yield os.path.join(root, name)


def test_no_native_dialogs_anywhere():
    # Native dialogs are banned app-wide: they block the JS thread on a slow
    # device and look nothing like the Talaria shell. In-page modals only.
    banned = re.compile(r"(?:^|[^\w.])(alert|prompt)\s*\(")
    bare_confirm = re.compile(r"(?:^|[^\w.])confirm\s*\(")
    hits = []
    for path in _ui_sources():
        src = _read(path)
        uses_modal_confirm = "useConfirm" in src
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if banned.search(line):
                hits.append("%s:%d %s" % (os.path.basename(path), line_no, stripped[:70]))
            elif bare_confirm.search(line) and not uses_modal_confirm:
                hits.append("%s:%d %s" % (os.path.basename(path), line_no, stripped[:70]))
    assert not hits, hits


def test_no_external_fetches_in_the_ui():
    # The device serves this app on an isolated LAN: no CDN, no bundled
    # webfonts. The single carve-out is the Config -> Theme font loader
    # (ui/src/lib/theme.ts), which fetches user-selected Google Fonts on
    # demand in the browser only — offline, the system stacks render.
    for path in _ui_sources():
        src = _read(path)
        if path.replace("\\", "/").endswith("lib/theme.ts"):
            assert "cdn." not in src, path
            continue
        assert "fonts.googleapis" not in src, path
        assert "cdn." not in src, path
    css = _read(os.path.join(WWW, "assets", "app.css"))
    assert "fonts.googleapis" not in css
    assert "url(http" not in css


def test_design_tokens_are_the_talaria_palette():
    css = _read(os.path.join(UI, "index.css"))
    assert "--background-base: #14161b" in css
    assert "--midground-base: #dfe3ea" in css
    # Square corners are part of the identity, not an accident.
    assert "--radius: 0px" in css


def test_clickable_actions_show_the_hand_cursor():
    # Tailwind v4's preflight resets buttons to the default arrow, which reads
    # as "not clickable" next to anchors. The base layer opts the whole element
    # back in, so no page needs a per-button cursor-pointer.
    css = _read(os.path.join(UI, "index.css"))
    assert re.search(r"button:not\(:disabled\)\s*\{\s*cursor:\s*pointer;", css), \
        "base layer must give enabled buttons the hand cursor"
    # The only allowed opt-out is the full-screen modal backdrop: a dismiss
    # layer, not an action, and a hand over the whole viewport would be noise.
    for root, _dirs, files in os.walk(UI):
        for fn in files:
            if not fn.endswith((".ts", ".tsx")):
                continue
            full = os.path.join(root, fn)
            if "cursor-default" in _read(full):
                assert "fixed inset-0" in _read(full), full


def test_no_legacy_token_storage_key_regression():
    # Existing browsers keep their unlock state across the upgrade.
    api = _read(os.path.join(UI, "lib", "api.ts"))
    assert "esp32_token" in api


def test_login_gate_shape():
    # /login is the Hermes-style gate: fixed admin identity, password field,
    # no sidebar chrome, locked devices redirect to it.
    app = _read(os.path.join(UI, "App.tsx"))
    assert "/login" in app and "LoginPage" in app
    login = _read(os.path.join(UI, "pages", "LoginPage.tsx"))
    assert "admin" in login
    assert 'name="username"' in login and 'name="password"' in login
    assert "unlock(username" in login or "unlock(" in login
    shell = _read(os.path.join(UI, "components", "Shell.tsx"))
    assert "'/login'" in shell or '"/login"' in shell
    assert "location.pathname === '/login'" in shell or 'location.pathname === "/login"' in shell


def test_agents_field_notes_describe_the_shipped_spa():
    # The field notes are the hand-off document: they must describe the
    # architecture that actually ships, not the retired hand-written pages.
    agents = _read(os.path.join(BASE, "AGENTS.md"))
    for mark in (
        "React SPA",
        "ui/",
        "prebuilt gzip twin",
        "catch-all registered LAST",
        "MAX_CONCURRENT = 1",
        "Nav ↔ route parity",
        "LENS_0",
        "no `alert`/`confirm`/`prompt`",
        "test_api_contract.py",
    ):
        assert mark in agents, mark
    for stale in ("shelled+dark now", "NAV-START", "all 18 pages"):
        assert stale not in agents, stale
