# delegate.py — one-level task delegation (Mini Hermes Phase 6). Slot 17.
# {task, tools_allow[]}. Sequential (no threads on MicroPython): the child runs
# agent_core.runTurn(task, history=[], max_iters=min(10, parent budget)) with a
# TOOL RESTRICTION active (agent_tools._ACTIVE_TOOL_ALLOW), restored via
# try/finally so a child crash can never wedge the parent's toolset.
#
# Child toolset policy:
# - restart_device is NEVER in a child (a reboot would kill the parent turn),
#   even when explicitly listed in tools_allow.
# - Default (no tools_allow): parent-enabled MINUS
#   {restart_device, gpio_write, delegate_task, exec_py}.
# - tools_allow[] is an INTERSECT filter over (parent-enabled minus
#   restart_device): explicitly listing gpio_write / delegate_task / exec_py
#   re-allows them for that child, but nothing parent-disabled can be added.
#   (Re-added delegate_task is still refused at call time by the depth flag.)
#
# Exit envelope into parent context: {exit, result} with exit in
# completed|max_iterations|interrupted|error and result capped at 1KB. Child
# exceptions become {exit: error} and never raise into the parent loop.
# "interrupted" is reserved for Hermes parity: the current child runner has no
# preemption point (one TLS-bound turn), so it is never produced here.
try:
    import ujson as json
except ImportError:
    import json

MAX_CHILDREN_PER_TURN = 2
CHILD_MAX_ITERS = 10
RESULT_CAP = 1024
TASK_MAX = 1500

_ALWAYS_EXCLUDED = ("restart_device",)
_DEFAULT_EXCLUDED = ("restart_device", "gpio_write", "delegate_task",
                     "exec_py")

_in_child = False  # depth flag: one level only
_child_count = 0  # per-parent-turn counter, reset by begin_turn()


def begin_turn():
    """Reset the per-parent-turn child counter. agent_core.runTurn calls this."""
    global _child_count
    _child_count = 0


def _reset():
    """Test hook: clear depth flag and turn counter."""
    global _in_child, _child_count
    _in_child = False
    _child_count = 0


def _parent_budget():
    try:
        import config
        n = int(config.agent_max_iters)
    except Exception:
        n = 3
    if n < 1:
        n = 1
    if n > 5:
        n = 5
    return n


def _classify(reply):
    try:
        s = str(reply or "")
    except Exception:
        return "error"
    if s.startswith("ERROR:"):
        return "error"
    if "(step budget reached before a summary)" in s:
        return "max_iterations"
    return "completed"


def _run(args):
    global _in_child, _child_count
    try:
        import agent_tools
    except Exception:
        return json.dumps({"success": False, "error": "tool host missing"})
    if not isinstance(args, dict):
        args = {}
    try:
        task = str(args.get("task", "") or "").strip()
    except Exception:
        task = ""
    if not task:
        return json.dumps({"success": False, "error": "task is required"})
    if len(task) > TASK_MAX:
        task = task[:TASK_MAX]
    if _in_child:
        return json.dumps({"success": False,
                           "error": "delegate_task nesting refused: one level "
                                    "only (a delegated turn cannot delegate)"})
    if _child_count >= MAX_CHILDREN_PER_TURN:
        return json.dumps({"success": False,
                           "error": "at most %d delegate_task calls per parent "
                                    "turn" % MAX_CHILDREN_PER_TURN})
    try:
        names = [t["name"] for i, t in enumerate(agent_tools.TOOL_REGISTRY)
                 if agent_tools.toolEnabledIdx(i)]
    except Exception:
        names = []
    base = [n for n in names if n not in _ALWAYS_EXCLUDED]
    want = args.get("tools_allow", None)
    if want is None:
        allow = [n for n in base if n not in _DEFAULT_EXCLUDED]
    else:
        if not isinstance(want, list):
            return json.dumps({"success": False,
                               "error": "tools_allow must be a list of tool names"})
        try:
            wset = [str(x) for x in want]
        except Exception:
            wset = []
        allow = [n for n in base if n in wset]
    ci = _parent_budget()
    if ci > CHILD_MAX_ITERS:
        ci = CHILD_MAX_ITERS
    _child_count += 1
    _in_child = True
    try:
        prev = getattr(agent_tools, "_ACTIVE_TOOL_ALLOW", None)
    except Exception:
        prev = None
    try:
        agent_tools._ACTIVE_TOOL_ALLOW = allow
    except Exception:
        pass
    try:
        import agent_core
        reply = agent_core.runTurn(task, history=[], max_iters=ci)
        exit_kind = _classify(reply)
    except Exception as e:
        reply = "child error: %s" % str(e)[:200]
        exit_kind = "error"
    finally:
        try:
            agent_tools._ACTIVE_TOOL_ALLOW = prev
        except Exception:
            pass
        _in_child = False
    try:
        text = str(reply or "")
    except Exception:
        text = ""
    trunc = len(text) > RESULT_CAP
    if trunc:
        text = text[:RESULT_CAP]
    return json.dumps({"success": exit_kind != "error", "exit": exit_kind,
                       "result": text, "truncated": trunc})


TOOL = {
    "name": "delegate_task",
    "ui_hint": "Delegate a subtask to a child turn (max 2 per turn)",
    "description": ("Delegate one subtask to a child agent turn with a fresh "
                    "context and a restricted toolset (default: no gpio_write, "
                    "restart_device, delegate_task or exec_py). One level only "
                    "(no nesting), max 2 children per parent turn, child budget "
                    "<= 10 iters, result capped at 1KB. Optional tools_allow[] "
                    "narrows the child toolset further (restart_device is never "
                    "allowed in a child). Use to collapse a multi-step device "
                    "chore into one call."),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "tools_allow": {"type": "array",
                            "items": {"type": "string"}},
        },
        "required": ["task"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
