# Tools — one module per function

Copy `_template.py.sample` to `tools/tool_mything.py`, fill in the 3 marked
spots, add one line to `tools/registry.py`. Done.

## Files

| File | What |
|------|------|
| `tools/tool_api.md` (this doc) | `TOOL` dict contract (`name`, `ui_hint`, `description`, `parameters`, `run`, `max_result_chars`). |
| `tools/registry.py` | Ordered list of tools. **Append-only** — order = bit in `tools_mask` (saved `/functions` toggles). |
| `tools/tool_*.py` | One tool each: `TOOL = {...}` with schema + `run(args)` executor. |
| `tools/_template.py.sample` | Starter, not imported (`.sample` so nothing loads it). |

## TOOL contract

```python
TOOL = {
    "name": "mything",            # unique, sent to the model
    "ui_hint": "One-line label",  # shown on /functions + /api/tools
    "description": "One sentence for the model.",
    "parameters": {               # OpenAI function parameters schema
        "type": "object",
        "properties": {"pin": {"type": "integer"}},
        "required": ["pin"],
    },
    "run": _run,                  # fn(dict) -> JSON string, small (<1KB)
    "max_result_chars": 1200,
}
```

## Add a tool

1. Copy template to `tools/tool_mything.py`.
2. Set name, schema, run logic.
3. `tools/registry.py`: add `from tools.tool_mything import TOOL as Tool_mything` + append `Tool_mything` at the END.
4. Deploy + toggle on `/functions`.
5. (Optional) add a row to `docs/agent-tools.md` catalogue in the C++ repo.

## Edit a tool

Just open its `tools/tool_*.py` — schema and behavior live together. Shared
policy (`pinCanWrite()` etc. in `agent_tools.py`) stays put.

## Limits

- `tools_mask` is an int bitmask — keep to 32 tools max (same as C++).
- Keep `run()` fast (< few seconds) and results < ~1KB (`max_result_chars`, 2200 for web text).
