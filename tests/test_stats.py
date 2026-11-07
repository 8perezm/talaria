import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import server

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_collect_stats_keys():
    s = server._collect_stats(False)
    for k in ("uptime_s", "uptime_human", "ram_free", "ram_alloc", "ram_total",
              "idf_heap", "cpu_freq", "unique_id", "flash_size", "mcu_temp_c",
              "board", "board_machine", "board_version", "platform", "mpy_version",
              "now", "fs_total", "fs_free", "fs_used", "log_bytes", "mem_bytes",
              "config_bytes", "chat_lines", "mem_facts", "fs_ok", "ap_mode",
              "wifi_connected", "ip", "mdns", "endpoint_configured", "endpoint",
              "model", "auth_required", "tools_mask", "ssid", "rssi", "mac",
              "ap_active", "ap_ip", "tools_enabled", "tools_total",
              "chip_s3", "pins_writable", "pins_adc", "i2c"):
        assert k in s, "missing key: %s" % k
    assert isinstance(s["ram_free"], int)
    assert isinstance(s["pins_writable"], list)
    assert isinstance(s["tools_enabled"], list)
    assert s["i2c"] is None
    s2 = server._collect_stats(True)
    assert isinstance(s2["i2c"], dict)


def test_collect_stats_json_serialisable():
    import json
    s = server._collect_stats(False)
    body = json.dumps(s)
    assert len(body) > 100


def test_stats_page_exists():
    src = open(os.path.join(ROOT, "www", "stats.html"), encoding="utf-8").read()
    assert "/api/stats" in src
    assert "i2cbtn" in src
    assert "<title>Agent — Stats</title>" in src


def test_stats_page_wide_grid():
    src = open(os.path.join(ROOT, "www", "stats.html"), encoding="utf-8").read()
    # full-width container + responsive multi-column grid (1/2/3 cols)
    assert "max-width:1440px" in src
    assert '<div class="grid">' in src
    assert "grid-template-columns" in src
    assert "@media(min-width:1000px)" in src
    assert "@media(min-width:1500px)" in src


def test_no_native_dialogs_in_stats():
    src = open(os.path.join(ROOT, "www", "stats.html"), encoding="utf-8").read()
    assert not re.search(r"\b(alert|confirm|prompt)\s*\(", src)


def test_chat_status_line_removed():
    src = open(os.path.join(ROOT, "www", "chat.html"), encoding="utf-8").read()
    # composer status line + its persistent IP/model/heap display are gone
    assert '<div id="status"></div>' not in src
    assert "getElementById('status')" not in src
    assert "KB heap" not in src
    assert "#status{" not in src
    # transient feedback now uses the auto-hiding toast
    assert 'id="toast"' in src
    assert "function toast(m)" in src
    # model picker + clear flows still give feedback
    assert "toast('Saving model" in src
    assert "toast('Chat cleared" in src


def test_nav_has_stats_everywhere():
    pages = glob.glob(os.path.join(ROOT, "www", "*.html"))
    assert len(pages) >= 9
    for p in pages:
        src = open(p, encoding="utf-8").read()
        assert 'href="/stats"' in src, "missing Stats nav in %s" % os.path.basename(p)


def test_routes_registered():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert '@app.get("/stats")' in src
    assert '@app.get("/api/stats")' in src
    assert "send_file(\"www/stats.html\")" in src
