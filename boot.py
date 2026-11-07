# boot.py — runs before main.py on MicroPython. Keep minimal.
# Enables PSRAM-friendly GC threshold on ESP32-S3 where available.
try:
    import gc
    gc.enable()
    try:
        gc.threshold(24576)
    except Exception:
        pass
except Exception:
    pass
