# tool_get_status — read-only device snapshot.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import config
    heap, uptime_s, wifi, rssi, ip = 0, 0, "", 0, "ap"
    try:
        import gc
        heap = gc.mem_free()
    except Exception:
        pass
    try:
        import time
        uptime_s = int(time.ticks_ms() // 1000) if hasattr(time, "ticks_ms") else 0
    except Exception:
        pass
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        if sta.isconnected():
            try:
                wifi = sta.config("essid")
            except Exception:
                wifi = ""
            try:
                ip = sta.ifconfig()[0]
            except Exception:
                pass
            try:
                rssi = sta.status("rssi")
            except Exception:
                rssi = 0
        else:
            try:
                ap = network.WLAN(network.AP_IF)
                if ap.active():
                    ip = ap.ifconfig()[0]
            except Exception:
                pass
    except Exception:
        pass
    out = {"heap": heap, "uptime_s": uptime_s, "wifi": wifi, "rssi": rssi,
           "ip": ip, "model": config.cfgModel}
    return json.dumps(out)


TOOL = {
    "name": "get_status",
    "ui_hint": "Heap, uptime, WiFi, IP",
    "description": "Get ESP32 status: heap, uptime, wifi, ip, model",
    "parameters": {"type": "object", "properties": {}},
    "run": _run,
    "max_result_chars": 1200,
}
