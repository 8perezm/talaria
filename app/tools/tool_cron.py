# tool_cron — scheduled agent turns, optionally running a workspace script
# (Mini Hermes Phase 5, script support for Hermes parity). Slot 15.
# {op: add|list|edit|pause|resume|remove|run_now, ...} over cron.py (shared
# handle() dispatcher — the same ops as POST /api/cron).
# add: {prompt, every_s (60..86400, clamped), deliver: log|webhook|telegram,
#        webhook_url, skills[], name?, script?, no_agent?} — max 5 jobs.
#   name: optional display label (<=60 chars). script: a workspace .py file
#   (e.g. workspace/hello.py). With no_agent=true the script runs INSTEAD of
#   the agent turn and its stdout is delivered verbatim; otherwise the script
#   output is prepended to the agent prompt. A job needs a prompt OR
#   (no_agent + script).
# edit: {id!, name?, prompt?, every_s?, deliver?, webhook_url?, skills?,
#   script?, no_agent?} (same validation; reschedules from now). script="" /
#   name="" clears. run_now forces one run without touching the schedule.
# Validation errors are returned, never raised.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    try:
        import cron as _cron
        if not isinstance(args, dict):
            args = {}
        return json.dumps(_cron.handle(args))
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "cron tool failed: %s" % str(e)[:120]})


TOOL = {
    "name": "cron",
    "ui_hint": "Schedule recurring agent turns or script runs (max 5 jobs)",
    "description": ("Manage scheduled jobs (max 5, every 60s..86400s). "
                    "Ops: add {name?, prompt, every_s, deliver?, webhook_url?, skills?, "
                    "script?, no_agent?}, list, edit {id, name?, prompt?, every_s?, "
                    "deliver?, webhook_url?, skills?, script?, no_agent?}, "
                    "pause {id}, resume {id}, remove {id}, run_now {id}. "
                    "name is an optional display label (<=60 chars). "
                    "script is a workspace .py file (e.g. workspace/hello.py): "
                    "with no_agent=true it runs INSTEAD of the agent turn and "
                    "stdout is delivered verbatim, otherwise the script output "
                    "is prepended to the agent prompt. A job needs a prompt OR "
                    "(no_agent + script). "
                    "Deliver targets: log (chat log), webhook (HTTP POST), "
                    "telegram (stored; delivery lands in Phase 8). "
                    "Use when the user wants something done on a schedule."),
    "parameters": {
        "type": "object",
        "properties": {
            "op": {"type": "string",
                   "enum": ["add", "list", "edit", "pause", "resume",
                            "remove", "run_now"]},
            "id": {"type": "string"},
            "name": {"type": "string"},
            "prompt": {"type": "string"},
            "every_s": {"type": "integer"},
            "deliver": {"type": "string",
                        "enum": ["log", "webhook", "telegram"]},
            "webhook_url": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "script": {"type": "string"},
            "no_agent": {"type": "boolean"},
        },
        "required": ["op"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
