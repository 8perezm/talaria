# net.py — WiFi STA + AP + captive-portal DNS.
# MicroPython port of src/net.h/.cpp.
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

apMode = False
dnsRunning = False
DNS_PORT = 53
_server_ip = "192.168.4.1"


def is_connected():
    try:
        import network
        return network.WLAN(network.STA_IF).isconnected()
    except Exception:
        return False


def connectWiFi(timeoutMs=15000):
    import config
    if not config.cfgSsid:
        return False
    try:
        import network
        import time
        sta = network.WLAN(network.STA_IF)
        try:
            sta.active(True)
        except Exception:
            pass
        # MicroPython: hostname for DHCP/mDNS-ish
        try:
            sta.config(dhcp_hostname=getattr(config, "cfgMdnsName",
                                            config.MDNS_NAME))
        except Exception:
            pass
        if sta.isconnected():
            try:
                print("WiFi OK:", sta.ifconfig()[0])
            except Exception:
                pass
            return True
        print("Connecting to %s ..." % config.cfgSsid)
        try:
            sta.connect(config.cfgSsid, config.cfgPass)
        except Exception as e:
            print("WiFi connect call failed:", e)
            return False
        t0 = time.ticks_ms() if hasattr(time, "ticks_ms") else 0

        def _elapsed():
            try:
                return time.ticks_diff(time.ticks_ms(), t0)
            except Exception:
                return 0
        while not sta.isconnected() and _elapsed() < timeoutMs:
            try:
                import time as _t
                _t.sleep(0.5)
                print(".", end="")
            except Exception:
                break
        print("")
        if sta.isconnected():
            try:
                print("WiFi OK:", sta.ifconfig()[0])
            except Exception:
                print("WiFi OK")
            return True
        print("WiFi failed")
        return False
    except Exception as e:
        print("WiFi failed:", e)
        return False


def startAP():
    global apMode, dnsRunning
    import config
    apMode = True
    try:
        import network
        ap = network.WLAN(network.AP_IF)
        ap_ssid = getattr(config, "cfgApSsid", config.AP_SSID)
        # Open network when password is empty: omit password entirely and force
        # AUTH_OPEN. Passing password="" would select WPA with an empty key,
        # which produces a broken/hidden AP on some builds.
        try:
            if config.AP_PASS:
                ap.config(essid=ap_ssid, password=config.AP_PASS)
            else:
                try:
                    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
                except Exception:
                    ap.config(essid=ap_ssid)
        except Exception:
            try:
                ap.config(essid=ap_ssid)
            except Exception:
                pass
        try:
            ap.active(True)
        except Exception as e:
            print("AP start failed:", e)
        try:
            print("AP net:", ap.ifconfig(), "essid=", ap.config("essid"),
                  "active=", ap.active())
        except Exception as e:
            print("AP info failed:", e)
        try:
            print("AP started: %s -> http://192.168.4.1/setup" % ap_ssid)
        except Exception:
            pass
    except Exception as e:
        print("AP start failed:", e)
    dnsRunning = True


def local_ip():
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        if sta.isconnected():
            return sta.ifconfig()[0]
        ap = network.WLAN(network.AP_IF)
        if ap.active():
            try:
                return ap.ifconfig()[0]
            except Exception:
                return _server_ip
    except Exception:
        pass
    return _server_ip if apMode else ""


# ---- minimal wildcard DNS server (answers every A query with AP IP) ----
async def _dns_server(ip=_server_ip):
    import socket
    print("[dns] wildcard -> %s :53" % ip)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except Exception as e:
        print("[dns] socket failed:", e)
        return
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    try:
        s.bind(("0.0.0.0", DNS_PORT))
    except Exception as e:
        print("[dns] bind failed:", e)
        return
    try:
        s.setblocking(False)
    except Exception:
        pass
    parts = [int(x) for x in ip.split(".")]
    rdata = bytes(parts)
    while True:
        try:
            data, addr = s.recvfrom(512)
        except Exception:
            await asyncio.sleep(0.05)
            continue
        try:
            if len(data) < 12:
                continue
            txid = data[:2]
            flags = b"\x81\x80"
            qd = data[4:6] or b"\x00\x01"
            an = b"\x00\x01"
            ns = b"\x00\x00"
            ar = b"\x00\x00"
            q = data[12:]
            # response: header + question + answer (pointer to name, A, IN, TTL 60, RDLEN 4, RDATA)
            resp = txid + flags + qd + an + ns + ar + q + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + rdata
            try:
                s.sendto(resp, addr)
            except Exception:
                pass
        except Exception:
            pass
        await asyncio.sleep(0)


def start_dns_task(ip=_server_ip):
    try:
        return asyncio.create_task(_dns_server(ip))
    except Exception as e:
        print("[dns] task start failed:", e)
        return None


# MicroPython's time.time() counts from 2000-01-01 on the ESP32 port (not
# 1970), so `> 1700000000` (a 1970-epoch value) could never trip before
# ~2053: every soft boot re-ran NTP and printed a scary failure whenever
# pool.ntp.org timed out. 2024-01-01 is 757382400s after 2000-01-01.
_PLAUSIBLE_TIME = 757382400


def syncTime(timeoutMs=8000):
    """Set the RTC from NTP — TLS needs a plausible date to handshake.

    The board boots at 2000-01-01, and mbedTLS refuses to negotiate certs
    against that. Called once at boot after WiFi is up; best-effort so a
    blocked NTP port never delays startup.
    """
    import time
    try:
        if time.time() > _PLAUSIBLE_TIME:
            return True
    except Exception:
        pass
    t0 = time.ticks_ms() if hasattr(time, "ticks_ms") else 0
    try:
        import ntptime
        try:
            ntptime.timeout = max(1, int(timeoutMs // 1000))
        except Exception:
            pass
        ntptime.settime()
        print("[ntp] time synced: %s" % (time.localtime()[:5],))
        return True
    except Exception as e:
        print("[ntp] sync failed:", str(e)[:60])
        return False


def try_start_mdns():
    """Best-effort mDNS. MicroPython core has none; skip gracefully."""
    try:
        # Some builds ship `mdns` or ESP-IDF bindings — use if present.
        import mdns  # noqa
        print("[mdns] module present (not started by default)")
    except Exception:
        print("[mdns] http://esp32-agent.local (mDNS not available on MicroPython; use IP)")


def ensure_dns(host="api.deepinfra.com"):
    """Make sure name resolution works; switch to public DNS if LAN DNS fails.

    The LAN resolver can stall (getaddrinfo has no timeout and blocks the
    server). Called once at boot: if the endpoint doesn't resolve, point
    the interface at 8.8.8.8 and re-test, else keep DHCP DNS.
    """
    import socket
    try:
        if socket.getaddrinfo(host, 443):
            return True
    except Exception as e:
        print("[net] LAN DNS failed (%s), trying 8.8.8.8" % str(e)[:60])
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        cur = sta.ifconfig()
        sta.ifconfig((cur[0], cur[1], cur[2], "8.8.8.8"))
    except Exception as e:
        print("[net] dns override failed:", e)
        return False
    try:
        if socket.getaddrinfo(host, 443):
            print("[net] DNS via 8.8.8.8 OK")
            return True
    except Exception as e:
        print("[net] public DNS also failing:", str(e)[:60])
    try:
        sta.ifconfig((cur[0], cur[1], cur[2], cur[3]))
    except Exception:
        pass
    return False
