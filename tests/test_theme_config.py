# test_theme_config.py — Config -> Theme settings (color scheme + fonts).
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config
import config_schema

BASE = os.path.join(os.path.dirname(__file__), "..")


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config.loadConfig()


def _theme_keys():
    return [f["key"] for f in config_schema.category_fields("theme")]


def test_theme_category_registered():
    assert "theme" in config_schema.CATEGORY_ORDER
    assert _theme_keys() == [
        "theme.color_scheme",
        "theme.font_headers",
        "theme.font_headers_size",
        "theme.font_body",
        "theme.font_body_size",
        "theme.font_mono",
        "theme.font_mono_size",
    ]
    cats = [c["id"] for c in config.form_payload()["categories"]]
    assert cats == list(config_schema.CATEGORY_ORDER)


def test_theme_defaults():
    assert config.cfgThemeScheme == "graphite"
    assert config.cfgThemeFontHeaders == "Poppins"
    assert config.cfgThemeHeadersSize == 15
    assert config.cfgThemeFontBody == "Space Grotesk"
    assert config.cfgThemeBodySize == 15
    assert config.cfgThemeFontMono == "JetBrains Mono"
    assert config.cfgThemeMonoSize == 13


def test_theme_save_round_trip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.save_form({
        "theme.color_scheme": "glacier",
        "theme.font_headers": "Space Grotesk",
        "theme.font_headers_size": 18,
        "theme.font_body": "Inter",
        "theme.font_body_size": 13,
        "theme.font_mono": "JetBrains Mono",
        "theme.font_mono_size": 12,
    })
    doc = config.read_doc()
    assert doc["theme"] == {
        "color_scheme": "glacier",
        "font_headers": "Space Grotesk",
        "font_headers_size": 18,
        "font_body": "Inter",
        "font_body_size": 13,
        "font_mono": "JetBrains Mono",
        "font_mono_size": 12,
    }
    assert config.cfgThemeScheme == "glacier"
    # unknown keys still rejected (strict save path)
    for bad in ({"theme.color_scheme": "nope"},
                {"theme.font_body": "Comic Sans"}):
        try:
            config.save_form(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for %r" % (bad,))
    # sizes clamp instead of raising (number type)
    config.save_form({"theme.font_headers_size": 99,
                      "theme.font_mono_size": 1})
    assert config.cfgThemeHeadersSize == 32
    assert config.cfgThemeMonoSize == 10


def _ts_block(name):
    src = open(os.path.join(BASE, "ui", "src", "lib", "theme.ts"),
               encoding="utf-8").read()
    start = src.index("const " + name)
    # Array / object literals end with a lone "]" / "}" line.
    m = re.search(r"\n(\]|\})", src[start:])
    assert m, name
    return src[start:start + m.start()]


def test_ts_theme_module_in_sync():
    # Scheme ids must match the backend select options exactly.
    ids = re.findall(r"\{\s*id: '([^']+)'", _ts_block("COLOR_SCHEMES"))
    assert ids == list(config_schema.THEME_SCHEME_IDS)
    assert len(ids) == 10
    lights = [m for m in re.finditer(r"light: (true|false)", _ts_block("COLOR_SCHEMES"))]
    assert len(lights) == 10
    assert sum(m.group(1) == "true" for m in lights) == 5
    # Font names must match the backend select options (System + 30 Google).
    sans = re.findall(r"name: '([^']+)'", _ts_block("SANS_FONTS"))
    mono = re.findall(r"name: '([^']+)'", _ts_block("MONO_FONTS"))
    assert sans == list(config_schema.THEME_SANS_FONTS)
    assert mono == list(config_schema.THEME_MONO_FONTS)
    assert len(sans) + len(mono) == 30
    assert "System Default" in open(
        os.path.join(BASE, "ui", "src", "lib", "theme.ts"),
        encoding="utf-8").read()
    defaults = _ts_block("THEME_DEFAULTS")
    assert re.search(r"scheme: 'graphite'", defaults)
    for key, want in (("fontHeaders", "Poppins"),
                      ("fontBody", "Space Grotesk"),
                      ("fontMono", "JetBrains Mono")):
        assert re.search(r"%s: '%s'" % (key, want), defaults), key
    for key, want in (("fontHeadersSize", "15"),
                      ("fontBodySize", "15"),
                      ("fontMonoSize", "13")):
        assert re.search(r"%s: %s" % (key, want), defaults), key
