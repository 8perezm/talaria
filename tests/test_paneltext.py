# test_paneltext.py - text rendering for the panel.
#
# The panel is 1-bit, so there is no antialiasing: quality comes from using
# the real bitmap faces in flash at native size or integer multiples. These
# tests pin the metrics and, importantly, the glyph orientation - the earlier
# memoryview-backed glyphs rendered mirrored/gar garbled on the panel.
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs  # noqa: E402

stubs.install()


class _FB(object):
    MONO_HLSB = 3
    MONO_HMSB = 4

    def __init__(self, buf, w, h, fmt=None):
        self.buf = buf
        self.w = w
        self.h = h
        self.rects = []

    def _stride(self):
        return (self.w + 7) // 8

    def fill(self, c):
        pass

    def text(self, s, x, y, c=1):
        # mark one lit pixel at (x, y), LSB-first packing
        if s:
            self.buf[y * self._stride() + x // 8] |= (1 << (x % 8))

    def pixel(self, x, y):
        b = self.buf[y * self._stride() + x // 8]
        return (b >> (x % 8)) & 1

    def fill_rect(self, x, y, w, h, c=1):
        self.rects.append((x, y, w, h, c))

    def rect(self, x, y, w, h, c=1):
        self.rects.append((x, y, w, h, c))


_fbmod = types.ModuleType("framebuf")
_fbmod.FrameBuffer = _FB
_fbmod.MONO_HLSB = 3
_fbmod.MONO_HMSB = 4
sys.modules.setdefault("framebuf", _fbmod)


def _fontmod(name, w, h, lit_col):
    """One glyph ('A'), with a single lit pixel at (lit_col, 0)."""
    mod = types.ModuleType(name)
    mod.WIDTH = w
    mod.HEIGHT = h
    mod.FIRST = 65
    mod.LAST = 65
    stride = (w + 7) // 8
    data = bytearray(h * stride)
    data[lit_col // 8] = 1 << (lit_col % 8)   # LSB = leftmost pixel
    mod.DATA = bytes(data)
    sys.modules[name] = mod
    return mod


_fontmod("font8x16", 8, 16, 7)
_fontmod("font16x32", 16, 32, 15)

import paneltext  # noqa: E402


def _canvas(w=960, h=540):
    return paneltext.Canvas(bytearray(w * h // 8), w, h)


def test_glyph_buffers_are_copies_not_memoryviews():
    f = paneltext._font("font16x32")
    for g in f["glyphs"]:
        assert isinstance(g.buf, bytearray)
    assert f["w"] == 16 and f["h"] == 32


def test_metrics_follow_the_font():
    c = _canvas()
    assert c.width("AAA", 16) == 3 * 8        # font8x16
    assert c.width("AAA", 32) == 3 * 16       # font16x32
    assert c.width("AAA", 64) == 3 * 32       # 2x
    assert c.width("AAA", 96) == 3 * 48       # 3x
    assert c.height(size=16) == 16
    assert c.height(size=96) == 96


def test_glyph_is_not_mirrored():
    # The only lit pixel is the rightmost column of the glyph. If the pixel
    # read were reversed it would land at x instead of x + 15*mult.
    c = _canvas()
    c.text("A", 0, 0, size=32)
    assert c.fb.rects == [(15, 0, 1, 1, 1)]


def test_integer_multiple_scales_the_cell():
    c = _canvas()
    c.text("A", 0, 0, size=96)            # 3x of 16x32
    assert c.fb.rects == [(45, 0, 3, 3, 1)]


def test_text_advances_by_the_font_width():
    c = _canvas()
    c.text("AA", 10, 20, size=32)
    assert [r[0] for r in c.fb.rects] == [10 + 15, 10 + 16 + 15]


def test_falls_back_to_the_8x8_cell_without_fonts():
    saved = {}
    for name in ("font8x16", "font16x32"):
        saved[name] = sys.modules.pop(name)
    paneltext._FONTS.clear()
    try:
        c = _canvas()
        assert c.width("AAA", 32) == 3 * 8 * 4
        c.text("A", 0, 0, size=32)
        assert c.fb.rects[0] == (0, 0, 4, 4, 1)
    finally:
        sys.modules.update(saved)
        paneltext._FONTS.clear()


def test_right_align_lands_on_the_edge():
    c = _canvas()
    c.right("AAA", 936, 100, size=32)      # 3 * 16 = 48
    assert c.fb.rects[0][0] == 936 - 48 + 15


def test_center_is_centered_in_the_panel():
    c = _canvas()
    c.center("AAAA", 40, size=32)          # 4 * 16 = 64
    assert c.fb.rects[0][0] == (960 - 64) // 2 + 15


def test_wrap_splits_on_words_and_respects_width():
    c = _canvas()
    lines = c.wrap("one two three four five six", 96, size=32)  # 6 chars
    assert len(lines) > 1
    for line in lines:
        assert c.width(line, 32) <= 96


def test_para_returns_the_y_below_the_block():
    c = _canvas()
    y = c.para("a b c d e f", 0, 10, 48, size=32, gap=6)
    assert y > 10


def test_open_canvas_uses_the_panel_size():
    calls = []

    class _Epd(object):
        MODE_GC16 = 2

        def init(self):
            calls.append("init")
            return 960, 540

        def fb(self):
            return bytearray(960 * 540 // 8)

    c, w, h = paneltext.open_canvas(_Epd())
    assert (w, h) == (960, 540) and calls == ["init"]
    assert c.w == 960 and c.h == 540
