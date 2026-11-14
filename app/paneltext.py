# paneltext.py - readable text on the 960x540 1-bit e-paper panel.
#
# Two font sources, in order of preference:
#   * the generated bitmap faces in flash (font8x16, font16x32) - a real
#     sans-serif design, native at 16px and 32px, scaled by integer steps for
#     larger sizes;
#   * framebuf's 8x8 cell as a fallback, which is legible but blocky.
#
#   import epd, paneltext
#   c, w, h = paneltext.open_canvas(epd)
#   c.text("BASINGSTOKE", 24, 10, size=32)
#   c.right("21C", w - 24, 90, size=96)
#   epd.update(epd.MODE_GC16)
#
# Only the first panel draw after a reboot is visible on this board: a later
# epd.init()+update() writes a fresh buffer but the driver sends the first one.
import framebuf

_FONTS = {}


def _font(name):
    """Per-glyph framebuffers for a generated font module (cached).

    Each glyph owns a bytearray copy. Building them over memoryview slices
    rendered garbled on the panel - this MicroPython does not honour a sliced
    view's offset inside FrameBuffer. A copy has no offset to ignore.
    """
    cached = _FONTS.get(name)
    if cached is not None:
        return cached
    mod = __import__(name)
    w = mod.WIDTH
    h = mod.HEIGHT
    first = mod.FIRST
    data = bytes(mod.DATA)
    step = h * ((w + 7) // 8)
    glyphs = []
    for i in range(mod.LAST - mod.FIRST + 1):
        chunk = bytearray(data[i * step:(i + 1) * step])
        glyphs.append(framebuf.FrameBuffer(chunk, w, h,
                                           framebuf.MONO_HLSB))
    font = {"w": w, "h": h, "first": first, "glyphs": glyphs}
    _FONTS[name] = font
    return font


def _pick(size):
    """(font, integer multiplier) or (None, scale) for the 8x8 fallback."""
    try:
        size = int(size)
    except Exception:
        size = 32
    if size <= 16:
        name, mult = "font8x16", 1
    elif size <= 32:
        name, mult = "font16x32", 1
    elif size <= 64:
        name, mult = "font16x32", 2
    else:
        name, mult = "font16x32", 3
    try:
        return _font(name), mult
    except Exception:
        pass
    scale = size // 8
    if scale < 1:
        scale = 1
    return None, scale


class Canvas(object):
    """Text over the panel's framebuffer."""

    def __init__(self, buf, w, h, fmt=None):
        if fmt is None:
            fmt = getattr(framebuf, "MONO_HMSB", framebuf.MONO_HLSB)
        self.fmt = fmt
        self.fb = framebuf.FrameBuffer(buf, w, h, fmt)
        self.w = w
        self.h = h
        self._tmp = framebuf.FrameBuffer(bytearray(8), 8, 8,
                                         framebuf.MONO_HLSB)

    # ---- measuring ----
    def width(self, s, size=32):
        font, mult = _pick(size)
        if font is None:
            return len(str(s)) * 8 * mult
        return len(str(s)) * font["w"] * mult

    def height(self, s=None, size=32):
        font, mult = _pick(size)
        if font is None:
            return 8 * mult
        return font["h"] * mult

    # ---- drawing ----
    def text(self, s, x, y, size=32, color=1):
        """Draw s at (x, y). Returns the x coordinate after the text."""
        s = str(s)
        font, mult = _pick(size)
        if font is None:
            return self._text8(s, x, y, mult, color)
        glyphs = font["glyphs"]
        first = font["first"]
        count = len(glyphs)
        gw = font["w"] * mult
        gh = font["h"]
        gwn = font["w"]
        cx = x
        for ch in s:
            o = ord(ch) - first
            if o < 0 or o >= count:
                o = ord("?") - first
                if o < 0 or o >= count:
                    o = 0
            g = glyphs[o]
            for row in range(gh):
                for col in range(gwn):
                    if g.pixel(col, row):
                        self.fb.fill_rect(cx + col * mult, y + row * mult,
                                          mult, mult, color)
            cx += gw
        return cx

    def _text8(self, s, x, y, scale, color):
        cx = x
        for ch in s:
            self._tmp.fill(0)
            self._tmp.text(ch, 0, 0, 1)
            for row in range(8):
                for col in range(8):
                    if self._tmp.pixel(col, row):
                        self.fb.fill_rect(cx + col * scale,
                                          y + row * scale,
                                          scale, scale, color)
            cx += 8 * scale
        return cx

    def right(self, s, x_right, y, size=32, color=1):
        return self.text(s, x_right - self.width(s, size), y, size, color)

    def center(self, s, y, size=32, color=1, x=0, w=None):
        w = self.w if w is None else w
        return self.text(s, x + (w - self.width(s, size)) // 2, y, size, color)

    # ---- paragraphs ----
    def wrap(self, s, max_w, size=32):
        words = str(s).replace("\n", " ").split(" ")
        lines = []
        cur = ""
        for word in words:
            if not word:
                continue
            trial = word if not cur else cur + " " + word
            if self.width(trial, size) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def para(self, s, x, y, max_w, size=32, gap=6, color=1, max_lines=8):
        yy = y
        lines = self.wrap(s, max_w, size)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        gh = self.height(size=size)
        for line in lines:
            self.text(line, x, yy, size, color)
            yy += gh + gap
        return yy

    # ---- decorations ----
    def rule(self, x, y, w, thickness=2, color=1):
        self.fb.fill_rect(x, y, w, thickness, color)

    def box(self, x, y, w, h, thickness=2, color=1):
        self.fb.rect(x, y, w, h, color)
        if thickness > 1:
            for i in range(1, thickness):
                self.fb.rect(x + i, y + i, w - 2 * i, h - 2 * i, color)


def open_canvas(epd):
    """epd.init() + a Canvas over its framebuffer. Returns (canvas, w, h).

    The caller still pushes the finished image with epd.update(epd.MODE_GC16).
    """
    w, h = epd.init()
    return Canvas(epd.fb(), w, h), w, h
