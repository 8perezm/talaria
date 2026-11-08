# tool_skill_view — load one full skill (<=3KB) on demand. Slot 13.
# {name} loads skills/<name>.md; "bundle:<name>" expands a bundles.json
# bundle instead (missing members skipped + noted, never fatal).
# Large bundle expansions are truncated to max_result_chars by execTool.
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import skillstore as _sk
    if not isinstance(args, dict):
        args = {}
    name = args.get("name", "")
    if name is None:
        name = ""
    name = str(name).strip()
    if not name:
        return json.dumps({"success": False,
                           "error": "name is required (or 'bundle:<name>')"})
    if name.startswith("bundle:"):
        return json.dumps(_sk.expand_bundle(name[7:].strip()))
    return json.dumps(_sk.view(name))


TOOL = {
    "name": "skill_view",
    "ui_hint": "Load a full skill by name",
    "description": ("Load the full text of one skill by name (first consult skills). "
                    "Use 'bundle:<name>' to expand a skill bundle; missing members are "
                    "skipped and noted. Load a skill when its summary matches the task, "
                    "then follow its Procedure and Verification sections."),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
    },
    "run": _run,
    "max_result_chars": 3500,
}
