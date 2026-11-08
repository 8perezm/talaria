# test_theme_fonts.py — the Config -> Theme fonts must reach EVERY page.
#
# The device dashboard has exactly three type roles, all driven by config.yaml:
#   theme.font_headers -> --theme-font-display (headings, labels, table heads)
#   theme.font_body    -> --theme-font-sans    (paragraphs, chat, buttons, inputs)
#   theme.font_mono    -> --theme-font-mono    (code, logs, editor)
# Nothing may hard-code a font family: a literal stack in a component is text
# that silently ignores the user's setting (the chat page was reported to do
# it). The rules below are the audit, so a regression fails here instead of in
# the browser.
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

BASE = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(BASE, "ui", "src")

ROLES = ("--theme-font-sans", "--theme-font-display", "--theme-font-mono")

# Inline styles are allowed only where the UI renders a *preview* of a font
# the user has not saved yet, and only through fontStack().
PREVIEW_FILE = os.path.join("pages", "ThemeSection.tsx")
# theme.ts owns the only font stacks in the app (the offline fallbacks).
STACK_OWNER = os.path.join("lib", "theme.ts")


def _read(*parts):
    with open(os.path.join(UI, *parts), encoding="utf-8") as f:
        return f.read()


def _walk():
    for root, _dirs, files in os.walk(UI):
        for fn in files:
            if fn.endswith((".ts", ".tsx", ".css")):
                full = os.path.join(root, fn)
                yield os.path.relpath(full, UI), full


# ---- the three roles exist and everything routes through them ----


def test_index_css_only_uses_theme_font_vars():
    css = _read("index.css")
    decls = [ln.strip() for ln in css.splitlines() if "font-family:" in ln]
    assert decls, "expected font-family declarations in index.css"
    for d in decls:
        assert any(v in d for v in ROLES) or d.endswith("font-family: inherit;"), d


def test_theme_tokens_are_declared_and_applied():
    css = _read("index.css")
    for role in ROLES:
        assert ("%s:" % role) in css, role
    theme = _read("lib", "theme.ts")
    for role in ROLES:
        assert "setProperty('%s'" % role in theme, role
    # Base size scales every rem-based utility in the bundle.
    assert "setProperty('--theme-base-size'" in theme


def test_no_component_hardcodes_a_font_family():
    offenders = []
    for rel, full in _walk():
        if rel == STACK_OWNER:
            continue
        with open(full, encoding="utf-8") as f:
            src = f.read()
        for m in re.finditer(r"fontFamily\s*:\s*([^,\n}]+)", src):
            value = m.group(1).strip()
            if rel == PREVIEW_FILE and value.startswith("fontStack("):
                continue
            offenders.append("%s: fontFamily: %s" % (rel, value))
        # A literal CSS stack in a style block would bypass the tokens too.
        for m in re.finditer(r"font-family\s*:\s*[^;'\"]+", src):
            value = m.group(0)
            if any(v in value for v in ROLES):
                continue
            # `inherit` follows whatever role the parent carries — never the UA font.
            if value.strip().rstrip(";").endswith("inherit"):
                continue
            offenders.append("%s: %s" % (rel, value))
    assert not offenders, "\n".join(offenders)


def test_heading_and_label_surfaces_use_the_display_role():
    css = _read("index.css")
    # One block per selector; font-family must be the display token inside it.
    for selector in (".label-display", ".panel-head", ".field-label", ".chip"):
        start = css.index(selector + " {")
        block = css[start:css.index("}", start)]
        assert "font-family: var(--theme-font-display)" in block, selector
    for selector in (".md h1", ".table th"):
        start = css.index(selector)
        block = css[start:css.index("}", start)]
        assert "font-family: var(--theme-font-display)" in block, selector
    # Code/log surfaces stay on the terminal role.
    assert "font-family: var(--theme-font-mono)" in css


def test_body_role_covers_the_document_and_form_controls():
    css = _read("index.css")
    html_start = css.index("html {")
    assert "font-family: var(--theme-font-sans)" in css[html_start:css.index("}", html_start)]
    body_start = css.index("body {")
    assert "font-family: var(--theme-font-sans)" in css[body_start:css.index("}", body_start)]
    # inputs/buttons inherit so they follow the body role, never the UA font.
    assert re.search(r"input,\s*\n\s*textarea,\s*\n\s*select,\s*\n\s*button \{\s*\n\s*font: inherit;", css)


# ---- the selected theme is on screen from the first paint ----


def test_theme_is_applied_before_the_first_render():
    main = _read("main.tsx")
    boot = main.index("applyBootTheme()")
    render = main.index("createRoot(")
    assert boot < render, "applyBootTheme() must run before createRoot().render()"


def test_theme_cache_round_trips_keys():
    theme = _read("lib", "theme.ts")
    assert "localStorage.setItem(THEME_CACHE_KEY" in theme
    assert "localStorage.getItem(THEME_CACHE_KEY" in theme
    for key in ("scheme", "fontHeaders", "fontHeadersSize", "fontBody",
                "fontBodySize", "fontMono", "fontMonoSize"):
        assert ("%s:" % key) in theme, key


def test_locked_views_use_the_cached_theme():
    applier = _read("components", "ThemeApplier.tsx")
    assert "loadThemeCache()" in applier
    # The unauthenticated branch must not reset a saved theme to defaults.
    unauth = applier[applier.index("if (!authed)"):]
    unauth = unauth[:unauth.index("}")]
    assert "loadThemeCache()" in unauth


# ---- sessions page: ordering + per-row export ----


def test_sessions_page_orders_and_exports_per_row():
    page = _read("pages", "SessionsPage.tsx")
    assert "'By date'" in page and "'Size'" in page
    assert "sortBy" in page and "sortDir" in page
    # Export is a row action now: one file per conversation, no page-level dump.
    assert "/api/sessions/export?id=" in page
    assert "exportOne(row)" in page
    assert "talaria-transcript.txt" not in page
    assert "log_tail.filter" not in page
    header = page[page.index("<PageHeader"):page.index("/>", page.index("<PageHeader"))]
    assert "Export" not in header
