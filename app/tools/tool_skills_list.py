# skills tool — L0 skills index + chat-side skill writes. Slot 12.
# Read path returns [{name, desc}] (prompt-sized, <=1KB rendered).
# {action: propose, name, content} stages a /learn draft through the same
# quarantine + approval path as skillstore.propose: staged drafts are NOT
# loadable via skill_view until a human approves them (/api/skills).
# {action: create|patch|delete, ...} goes through skillstore.create/patch/
# delete, which respect security.skills_write_approval: with approval on
# (the default) the write is STAGED for review in Skills, with approval off
# it applies immediately. Quarantine + name/size checks run either way.
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
    if act == "create":
        name = args.get("name", "")
        content = args.get("content", args.get("text", ""))
        if name is None:
            name = ""
        if content is None:
            content = ""
        return json.dumps(_sk.create(str(name), str(content)))
    if act == "patch":
        name = args.get("name", "")
        old = args.get("old_text", args.get("old", ""))
        new = args.get("content", args.get("new_text",
                                           args.get("new", args.get("text", ""))))
        if name is None:
            name = ""
        if old is None:
            old = ""
        if new is None:
            new = ""
        return json.dumps(_sk.patch(str(name), str(old), str(new)))
    if act == "delete":
        name = args.get("name", "")
        if name is None:
            name = ""
        return json.dumps(_sk.delete(str(name)))
    if act in ("list", "index", ""):
        items = _sk.index()
        return json.dumps({"success": True, "skills": items, "count": len(items)})
    return json.dumps({"success": False,
                        "error": "Unknown action '%s'. Use: list, propose, create, patch, delete" % act[:40]})


TOOL = {
    "name": "skills",
    "ui_hint": "List skills / create or revise skills",
    "description": ("List available skills (names + one-line summaries). "
                    "When the user asks to save a procedure as a reusable skill, "
                    "draft the full text (first line '// desc: <summary, <=120 chars>', "
                    "then Title / When to use / Procedure / Pitfalls / Verification, "
                    "<=3KB, lowercase-hyphen name) and call {action: create, name, content} "
                    "(or {action: propose, ...} for a /learn draft). "
                    "Revise with {action: patch, name, old_text, content} (old_text must "
                    "occur exactly once) or remove with {action: delete, name}. "
                    "Writes are quarantine-scanned; with write-approval on (default) "
                    "they are STAGED for human approval in Skills and not loadable "
                    "until approved — tell the user to approve there."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list", "propose", "create", "patch", "delete"]},
            "name": {"type": "string"},
            "content": {"type": "string"},
            "text": {"type": "string"},
            "old_text": {"type": "string"},
            "old": {"type": "string"},
            "new_text": {"type": "string"},
            "new": {"type": "string"},
        },
    },
    "run": _run,
    "max_result_chars": 1200,
}
