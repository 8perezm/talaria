# main.py — boot. Runs on the ESP32 (MicroPython runs main.py at power-on).
# Mirrors src/main.cpp: config -> fs -> wifi/AP -> mdns -> routes -> serve.
try:
    import logbuf
    logbuf.install()  # mirror serial print() into the /api/logs ring buffer
except Exception:
    pass
print("\n=== Agent boot == (MicroPython) ===")

import config
import agent_tools
from tools import registry as tools_registry

tools_registry.register_into_agent_tools()
config.loadConfig()
agent_tools.initAgentFS()

import net

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


async def _wifi_watchdog():
    import time
    while True:
        await asyncio.sleep(30)
        try:
            if not net.apMode:
                import network
                sta = network.WLAN(network.STA_IF)
                if not sta.isconnected():
                    print("WiFi lost, reconnecting...")
                    try:
                        sta.disconnect()
                    except Exception:
                        pass
                    try:
                        sta.reconnect()
                    except Exception:
                        try:
                            sta.connect(config.cfgSsid, config.cfgPass)
                        except Exception as e:
                            print("reconnect failed:", e)
        except Exception as e:
            print("watchdog:", e)


async def _cron_tick_loop():
    # Lazy import: a broken cron.py must never break boot. Any per-tick
    # failure is caught below so a cron crash can NEVER kill the server.
    try:
        import cron as _cron
    except Exception as e:
        print("[cron] disabled:", e)
        return
    while True:
        await asyncio.sleep(60)
        try:
            _cron.run_due()
        except Exception as e:
            print("[cron] tick failed:", e)


async def _tg_poll_loop():
    # Lazy import: a missing/broken gateway.py must never break boot. Any
    # per-pass failure is caught below so a Telegram crash can NEVER kill
    # the server. tg_loop() is one poll pass (dormant when no bot_token);
    # the ~30s cadence lives here, mirroring _cron_tick_loop.
    try:
        import gateway as _gw
    except Exception as e:
        print("[tg] disabled:", e)
        return
    while True:
        await asyncio.sleep(30)
        try:
            _gw.tg_loop()
        except Exception as e:
            print("[tg] pass failed:", e)


async def _amain():
    ok = net.connectWiFi(15000)
    if not ok:
        net.startAP()
    else:
        try:
            import network
            network.WLAN(network.STA_IF).active(True)
        except Exception:
            pass
        net.ensure_dns()
        net.syncTime()
    # STA responsiveness over power-save (mirrors WiFi.setSleep(false))
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        try:
            sta.config(pm=sta.PM_NONE)
        except Exception:
            pass
    except Exception:
        pass
    net.try_start_mdns()

    if net.apMode:
        print("Mode: AP-SETUP (http://192.168.4.1/setup)")
        try:
            net.start_dns_task()
        except Exception as e:
            print("[dns] failed:", e)
    else:
        print("Mode:", net.local_ip())

    print("endpoint %s | model %s" % (
        config.cfgEndpoint if config.cfgEndpoint else "(not set)", config.cfgModel))

    import server
    app = server.get_app()
    asyncio.create_task(_wifi_watchdog())
    asyncio.create_task(_cron_tick_loop())
    asyncio.create_task(_tg_poll_loop())
    # Microdot asyncio: prefer start_server so our tasks keep running.
    # If the server loop ever returns (a handler error that escaped Microdot,
    # or a transient lwIP failure), restart it instead of silently dropping
    # to the REPL — a device that answers "connection refused" until someone
    # presses RESET is indistinguishable from a crash.
    while True:
        try:
            await app.start_server(host="0.0.0.0", port=80)
            print("server loop returned; restarting in 2s")
        except AttributeError:
            # old/sync API — blocks; watchdog/DNS already scheduled where possible
            app.run(host="0.0.0.0", port=80)
            print("sync server returned; restarting in 2s")
        except Exception as e:
            print("server failed:", e)
        await asyncio.sleep(2)


try:
    asyncio.run(_amain())
except KeyboardInterrupt:
    raise
except Exception as e:
    # Do NOT reset immediately: a persistent boot error (e.g. a truncated
    # file) would become an unbreakable reset loop. Wait 15s so Ctrl-C over
    # serial reliably lands in REPL for repairs; reset only if untouched.
    print("fatal:", e)
    try:
        import time
        time.sleep(15)
    except KeyboardInterrupt:
        raise
    try:
        import machine
        machine.reset()
    except Exception:
        pass
