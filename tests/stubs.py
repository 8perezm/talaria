# stubs.py — CPython stand-ins for MicroPython-only modules so tests run on PC.
import sys
import types
import json as _json


def install():
    # --- machine ---
    if "machine" not in sys.modules:
        m = types.ModuleType("machine")

        class Pin:
            IN = 0
            OUT = 1
            _levels = {}

            def __init__(self, pin, mode=None):
                self.pin = pin
                self.mode = mode

            def value(self, v=None):
                if v is None:
                    return Pin._levels.get(self.pin, 0)
                Pin._levels[self.pin] = v
                return v

            def on(self):
                self.value(1)

            def off(self):
                self.value(0)

        class ADC:
            ATTN_11DB = 3

            def __init__(self, pin):
                self.pin = pin

            def atten(self, a):
                pass

            def read(self):
                return 1234

            def read_u16(self):
                return 1234 * 16

        def _reset():
            raise RuntimeError("reset stub")

        m.Pin = Pin
        m.ADC = ADC
        m.reset = _reset
        sys.modules["machine"] = m
    # --- network ---
    if "network" not in sys.modules:
        n = types.ModuleType("network")
        n.STA_IF = 0
        n.AP_IF = 1

        class WLAN:
            PM_NONE = 1

            def __init__(self, kind):
                self.kind = kind
                self._active = False

            def active(self, v=None):
                if v is None:
                    return self._active
                self._active = bool(v)
                return self._active

            def isconnected(self):
                return False

            def connect(self, *a, **k):
                pass

            def disconnect(self):
                pass

            def reconnect(self):
                pass

            def config(self, *a, **k):
                if a and isinstance(a[0], str) and not k:
                    return ""
                return None

            def ifconfig(self):
                return ("0.0.0.0",) * 4

            def scan(self):
                return []

            def status(self, *a):
                return 0

        n.WLAN = WLAN
        sys.modules["network"] = n
    # --- urequests (redirect to requests if available, else stub) ---
    if "urequests" not in sys.modules:
        try:
            import requests as _r  # noqa
            sys.modules["urequests"] = _r
        except Exception:
            u = types.ModuleType("urequests")

            class _Resp:
                status_code = 200
                text = "{}"
                content = b"{}"

                def close(self):
                    pass

            def _fail(*a, **k):
                raise RuntimeError("urequests stub: no network in tests")

            u.get = _fail
            u.post = _fail
            sys.modules["urequests"] = u
    # --- uasyncio -> asyncio ---
    if "uasyncio" not in sys.modules:
        import asyncio as _a
        sys.modules["uasyncio"] = _a
    # --- ujson -> json ---
    if "ujson" not in sys.modules:
        sys.modules["ujson"] = _json
