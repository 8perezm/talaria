# mip_install.py — run ONCE on the device (via mpremote) to fetch Microdot.
# Run AFTER MicroPython firmware is flashed and WiFi is up is NOT required:
# mip needs network, so easiest is to install from your PC with:
#   mpremote mip install github:miguelgrinberg/microdot/src/microdot
# This file is the on-device fallback: `mpremote run mip_install.py`
try:
    import mip
except ImportError:
    print("mip module not available on this MicroPython build.")
    raise SystemExit(1)

# base framework (required)
mip.install("github:miguelgrinberg/microdot/src/microdot/microdot.py") if False else None
# The github: spec installs the whole package dir on recent mip:
try:
    mip.install("github:miguelgrinberg/microdot/src/microdot")
    print("microdot installed. Reset the device.")
except Exception as e:
    print("mip install failed:", e)
    print("Alternative (from PC):")
    print('  mpremote mip install github:miguelgrinberg/microdot/src/microdot')
