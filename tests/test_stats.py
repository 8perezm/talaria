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












