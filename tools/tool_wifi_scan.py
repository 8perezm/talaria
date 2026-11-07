# tool_wifi_scan — scan nearby networks (blocking ~2s), top 10.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    out = {}
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        was_active = sta.active()
        if not was_active:
            try:
                sta.active(True)
            except Exception:
                pass
        nets = sta.scan()
        arr = []
        for n in nets[:10]:
            try:
                ssid = n[0].decode() if isinstance(n[0], bytes) else str(n[0])
            except Exception:
                ssid = ""
            try:
                rssi = int(n[3])
            except Exception:
                rssi = 0
            arr.append({"ssid": ssid, "rssi": rssi})
        out["networks"] = arr
        out["count"] = len(nets)
    except Exception as e:
        out["error"] = "scan failed: %s" % str(e)[:120]
    return json.dumps(out)


TOOL = {
    "name": "wifi_scan",
    "ui_hint": "Scan networks (~2s)",
    "description": "Scan nearby WiFi networks (takes ~2s).",
    "parameters": {"type": "object", "properties": {}},
    "run": _run,
    "max_result_chars": 1200,
}
