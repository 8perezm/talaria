# tool_cron — scheduled agent turns (Mini Hermes Phase 5). Slot 15.
# {op: add|list|edit|pause|resume|remove|run_now, ...} over cron.py (shared
# handle() dispatcher — the same ops as POST /api/cron).
# add: {prompt!, every_s (60..86400, clamped), deliver: log|webhook|telegram,
#        webhook_url, skills[]} — max 5 jobs. edit: {id!, prompt?, every_s?,
#        deliver?, webhook_url?, skills?} (same validation; reschedules from
#        now). run_now forces one run without touching the schedule.
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
    "ui_hint": "Schedule recurring agent turns (max 5 jobs)",
    "description": ("Manage scheduled agent jobs (max 5, every 60s..86400s). "
                    "Ops: add {prompt, every_s, deliver?, webhook_url?, skills?}, "
                    "list, edit {id, prompt?, every_s?, deliver?, webhook_url?, skills?}, "
                    "pause {id}, resume {id}, remove {id}, run_now {id}. "
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
            "prompt": {"type": "string"},
            "every_s": {"type": "integer"},
            "deliver": {"type": "string",
                        "enum": ["log", "webhook", "telegram"]},
            "webhook_url": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["op"],
    },
    "run": _run,
    "max_result_chars": 1200,
}
