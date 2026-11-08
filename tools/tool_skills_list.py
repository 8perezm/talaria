# tool_skills_list — L0 skills index + /learn draft staging. Slot 12.
# Read path returns [{name, desc}] (prompt-sized, <=1KB rendered).
# {action: propose, name, content} stages a /learn draft through the same
# quarantine + approval path as skillstore.propose: staged drafts are NOT
# loadable via skill_view until a human approves them (/api/skills).
try:
    import ujson as json
except ImportError:
    import json


def _run(args):
    import skillstore as _sk
    if not isinstance(args, dict):
        args = {}
    act = str(args.get("action", "") or "list").strip().lower()
    if act in ("propose", "stage", "stage_draft"):
        name = args.get("name", "")
        content = args.get("content", args.get("text", ""))
        if name is None:
            name = ""
        if content is None:
            content = ""
        return json.dumps(_sk.propose(str(name), str(content)))
    if act in ("list", "index", ""):
        items = _sk.index()
        return json.dumps({"success": True, "skills": items, "count": len(items)})
    return json.dumps({"success": False,
                       "error": "Unknown action '%s'. Use: list, propose" % act[:40]})


TOOL = {
    "name": "skills_list",
    "ui_hint": "List skills / propose a /learn draft",
    "description": ("List available skills (names + one-line summaries). "
                    "When the user asks to save a procedure (/learn), draft the full "
                    "SKILL.md text and call {action: propose, name, content}: the draft "
                    "is quarantine-scanned and STAGED for human approval, never applied "
                    "directly, and not loadable until approved."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "propose"]},
            "name": {"type": "string"},
            "content": {"type": "string"},
            "text": {"type": "string"},
        },
    },
    "run": _run,
    "max_result_chars": 1200,
}
