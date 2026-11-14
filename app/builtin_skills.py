# builtin_skills.py - skills shipped with the firmware.
#
# skillstore.ensure_builtin() materialises these into opt/data/skills/ once
# per BUILTIN_VERSION (marker: opt/data/skills/.builtin, which also records a
# hash of each copy we wrote so a bump can replace an untouched builtin while
# leaving a user edit alone).
#
# Keeping the text in code means a new board gets the display API without a
# separate upload, and the agent does not have to spend tool rounds
# rediscovering /app/paneltext.py, /app/screen.py and /app/epd.py.
#
# Content rules: <=3072 bytes, first line "// desc: ..." (<=120 chars), and
# the sections Title / When to use / Procedure / Pitfalls / Verification.
# Stored skills pass skillstore.scan(), so no blocked code/exfil patterns.

BUILTIN_VERSION = 5

SCREEN_SKILL = """// desc: Readable dashboard on the 960x540 e-paper panel (paneltext/epd)
# E-paper screen (4.7 inch, 960x540, 1-bit)

## When to use
Use when asked to show, draw or display something on the device screen, or to
build a dashboard, clock, chart, weather panel or status page.

## Procedure
1. Raw framebuf text is 8x8 and unreadable on this panel. Always use the
   helper, which draws from the real flash fonts (font8x16/font16x32):
     import epd, paneltext
     c, w, h = paneltext.open_canvas(epd)
     c.text("BASINGSTOKE", 24, 10, size=32)
     c.center("TODAY", 64, size=32)
     c.right("21C", w - 24, 110, size=96)
     c.para("long text wraps onto lines", 24, 260, 400, size=32)
     c.box(24, 66, 440, 400, 3)
     epd.update(epd.MODE_GC16)
2. Sizes: 16 and 32 are native (crisp); 64 = 2x and 96 = 3x of the 32px
   font. Ask only for 16/32/64/96 - the panel is 1-bit and cannot
   antialias, so non-integer scaling looks mushy. Width is
   len(text) * 8 cells at size 16, * 16 at size 32, * 32 at size 64.
3. c.fb is the raw framebuf for hline/rect/vline if you need them.
4. Finish with epd.update(epd.MODE_GC16). Without it the panel keeps the old
   image and nothing appears. Then print("panel updated").
5. Scripts live in the workspace: build with write_file append=true, then
   run_script. Output is capped at 1KB, so print a short summary.
6. run_script calls epd.deinit() afterwards; the image stays on the panel.
7. Revising a dashboard you wrote: rewrite it with write_file rather than
   paging through it with read_file. Reading slices back into the request
   makes it large enough that the model call starts timing out. Only read
   when you need to patch one specific line.

## Data
   from tools.tool_web_fetch import fetch_raw
   data = json.loads(fetch_raw(url).decode())
Ask Open-Meteo only for the fields you draw, so the body stays small.

## Pitfalls
- Missing epd.update() is the most common failure: it draws into a buffer and
  the screen looks unchanged.
- MicroPython has NO time.strftime: build clock strings from localtime().
- Each epd.init() costs about 1MB and is never returned, so at most two draws
  per boot. If a run reports "panel memory exhausted", reboot (the image
  survives) before drawing again.
- Keep text ASCII. Expand abbreviations and drop columns rather than shrink
  below scale 2.
- Do not call epd.init/update inside a per-item loop.

## Verification
run_script returns {"success": true, "output": "..."} and the panel repaints.
If a name is unclear, read /app/paneltext.py first instead of guessing.
"""

SKILLS = {"screen": SCREEN_SKILL}
