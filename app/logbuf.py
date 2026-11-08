# logbuf.py — in-memory ring buffer for device logs (console view backend).
#
# All firmware log output today goes to serial via print() ([agent], [tool],
# [net], [chat], ...). The web console needs that same text over HTTP, so
# install() wraps builtins.print once at boot: serial behaviour is unchanged,
# and every line is also kept in a small capped list served by /api/logs.
#
# MicroPython notes: plain list only (no collections.deque), % formatting,
# utf-8 only. ~250 lines x ~240 chars ~= 60KB worst case — fine on the
# SPIRAM_OCT build (~8MB heap), never read whole files into RAM here.

MAX_LINES = 250
MAX_LINE = 240

_BUF = []
_SEQ = 0
# True while the last print() left its line unterminated (end=""), so the
# next fragment continues the same terminal line instead of starting a new
# log entry (e.g. net.py's print(".", end="") progress dots).
_OPEN = False
_installed = False
_orig_print = None


def _truncate(s):
    if len(s) > MAX_LINE:
        return s[:MAX_LINE]
    return s


def push(msg):
    """Append one log line. Multi-line input is split. Never raises."""
    global _SEQ, _OPEN
    try:
        s = msg if isinstance(msg, str) else str(msg)
    except Exception:
        try:
            s = "(unprintable)"
        except Exception:
            return 0
    parts = s.split("\n")
    last_seq = 0
    for part in parts:
        # skip the empty tail of a trailing newline ("a\n" -> ["a", ""])
        if part == "" and len(parts) > 1:
            continue
        _SEQ += 1
        _BUF.append((_SEQ, _truncate(part)))
        last_seq = _SEQ
        while len(_BUF) > MAX_LINES:
            try:
                _BUF.pop(0)
            except Exception:
                break
    _OPEN = False
    return last_seq


def push_continue(msg):
    """Append to the last line (for print(..., end="")). Never raises."""
    try:
        s = msg if isinstance(msg, str) else str(msg)
    except Exception:
        return push(msg)
    if not _BUF:
        return push(s)
    try:
        seq, cur = _BUF[-1]
        _BUF[-1] = (seq, _truncate(cur + s))
        return seq
    except Exception:
        return push(s)


def get(since=0, limit=150):
    """Return (entries, seq): entries=[{seq, msg}] with seq > since."""
    try:
        since = int(since)
    except Exception:
        since = 0
    try:
        limit = int(limit)
    except Exception:
        limit = 150
    if limit < 1:
        limit = 1
    if limit > 300:
        limit = 300
    out = []
    for seq, msg in _BUF:
        try:
            if seq > since:
                out.append({"seq": seq, "msg": msg})
        except Exception:
            continue
    if len(out) > limit:
        out = out[-limit:]
    return out, _SEQ


def clear():
    """Empty the buffer. The sequence stays monotonic so pollers resync."""
    global _OPEN
    try:
        del _BUF[:]
    except Exception:
        pass
    _OPEN = False
    return _SEQ


def count():
    try:
        return len(_BUF)
    except Exception:
        return 0


def _fmt_args(a, k):
    try:
        sep = k.get("sep", " ")
        if sep is None:
            sep = " "
    except Exception:
        sep = " "
    try:
        parts = [str(x) for x in a]
    except Exception:
        parts = ["?"]
    try:
        return sep.join(parts)
    except Exception:
        return parts[0] if parts else ""


def install():
    """Wrap builtins.print so serial output is also buffered. Idempotent."""
    global _installed, _orig_print
    if _installed:
        return True
    try:
        import builtins
    except ImportError:
        return False
    try:
        orig = builtins.print
    except Exception:
        return False
    try:
        import sys as _sys
        _stdout = _sys.stdout
    except Exception:
        _stdout = None

    def _wrapped(*a, **k):
        global _OPEN
        try:
            f = k.get("file", None)
            if f is None or f is _stdout:
                try:
                    end = k.get("end", "\n")
                except Exception:
                    end = "\n"
                text = _fmt_args(a, k)
                if end == "" or end == "\r":
                    # unterminated fragment: continue the terminal line
                    if _OPEN:
                        push_continue(text)
                    else:
                        push(text)
                    _OPEN = True
                else:
                    if _OPEN:
                        # newline print closes the open line (real terminal
                        # shows "dots" + "done\n" on one line)
                        if text:
                            push_continue(text)
                        _OPEN = False
                    elif text or a:
                        push(text)
        except Exception:
            pass
        return orig(*a, **k)

    try:
        builtins.print = _wrapped
    except Exception:
        return False
    _orig_print = orig
    _installed = True
    return True
