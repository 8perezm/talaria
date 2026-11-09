# exec_py.py — constrained exec (Mini Hermes Phase 6). Slot 18, DEFAULT-OFF.
# {code}. Pure-computation snippets only (math, strings, lists). The blocklist
# below is a SUBSTRING scan (no `re` on MicroPython) over whitespace-collapsed
# text, so `import  os` / `from<TAB>machine` spacing evasions still match.
# It is NOT a sandbox: MicroPython has no timeout preemption (a hung snippet
# hangs the turn) and introspection tricks (getattr, crafted eval strings)
# are not scanned. TRUSTED-MODEL-ONLY: deliberately excluded from the fresh
# default mask and never auto-enabled onto stored masks (see config.py); the
# user enables it on /functions. Code <= 2KB, captured print output <= 1KB.
try:
    import ujson as json
except ImportError:
    import json

CODE_MAX = 2048
OUT_MAX = 1024

_BLOCKED = ("import machine", "import network", "import os", "import uos",
            "import sys", "from machine", "from network", "from os",
            "from uos", "from sys", "__import__", "open(", "exec(",
            "eval(", "compile(")


def blocked_hit(code):
    """Blocked substring in code, or '' when clean. Never raises."""
    try:
        flat = " ".join(str(code).split())
    except Exception:
        return "unreadable code"
    for p in _BLOCKED:
        if p in flat:
            return p
    return ""


def run_code(code):
    try:
        src = str(code or "")
    except Exception:
        return {"success": False, "error": "code is required"}
    if not src.strip():
        return {"success": False, "error": "code is required"}
    if len(src) > CODE_MAX:
        return {"success": False,
                "error": "code too long (%d chars, max %d)"
                         % (len(src), CODE_MAX)}
    hit = blocked_hit(src)
    if hit:
        return {"success": False,
                "error": "blocked pattern '%s': hardware/os/io/introspection "
                         "calls are not allowed in exec_py" % hit}
    lines = []

    def _emit(*a, **k):
        try:
            lines.append(" ".join(str(x) for x in a))
        except Exception:
            pass

    try:
        exec(src, {"print": _emit})
    except Exception as e:
        return {"success": False,
                "error": "exec failed: %s" % str(e)[:200]}
    out = "\n".join(lines)
    trunc = False
    if len(out) > OUT_MAX:
        out = out[:OUT_MAX]
        trunc = True
    return {"success": True, "output": out, "truncated": trunc}


def _run(args):
    try:
        if not isinstance(args, dict):
            args = {}
        return json.dumps(run_code(args.get("code", "")))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "exec_py failed: %s" % str(e)[:120]})


TOOL = {
    "name": "exec_py",
    "ui_hint": "Run a pure-computation Python snippet (trusted only)",
    "description": ("Run a short pure-computation Python snippet (math, strings, "
                    "lists; print() to capture output). Hardware, os, file and "
                    "introspection calls are blocked; code <= 2KB, output <= 1KB. "
                    "No timeout exists on MicroPython, so only use for quick "
                    "trusted calculations. Disabled by default — enable on "
                    "/functions deliberately."),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
        },
        "required": ["code"],
    },
    "run": _run,
    "max_result_chars": 1200,
    "default_off": True,
}
