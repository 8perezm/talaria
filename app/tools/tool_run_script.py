# tool_run_script.py - execute a workspace script on the device.
#
# One call instead of the cron add/run_now/remove dance: write the script with
# write_file, then run it here. The script runs in the same interpreter as the
# agent, so it can import and use the device's own modules.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    try:
        path = args.get("path", "")
        if not isinstance(path, str):
            path = str(path)
        path = path.strip()
    except Exception:
        return json.dumps({"success": False, "error": "invalid arguments"})
    if not path:
        return json.dumps({"success": False, "error": "path is required"})

    try:
        import cron
        ok, out = cron.run_script_file(path)
    except Exception as e:
        return json.dumps({"success": False,
                           "error": "runner unavailable: %s" % str(e)[:120]})

    res = {"success": bool(ok), "path": path}
    if ok:
        res["output"] = out
    else:
        res["error"] = out
    return json.dumps(res)


TOOL = {
    "name": "run_script",
    "ui_hint": "Run a workspace script",
    "description": (
        "Run a Python script that lives in the agent workspace and return its "
        "printed output. The script runs in-process on the device, so it can "
        "import and use the device's own modules. Use write_file to create or "
        "update the script first. Limits: 8 KB of source, 1 KB of captured "
        "output. Paths are workspace-relative: 'clock.py' and "
        "'workspace/clock.py' are the same file."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Workspace script path, e.g. clock.py"},
        },
        "required": ["path"],
    },
    "run": _run,
    "max_result_chars": 1400,
}
