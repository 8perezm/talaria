# conftest.py — host-side (CPython) test path setup.
# Application code lives in app/ (device: /app, on sys.path via main.py).
# Tests import flat names (`import config`, `from tools import registry`),
# so the app dir must be importable here too.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app"))
