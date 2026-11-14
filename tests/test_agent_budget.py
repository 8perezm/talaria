# test_agent_budget.py — the agentic loop's output and tool budgets.
#
# The failures this pins were real: every completion used 800 tokens (which
# includes reasoning and the whole tool-call arguments string), truncated
# arguments became `{}` and surfaced as a misleading "invalid path", and a
# shared 25s tool budget silently skipped the tools after a slow one while
# still listing them as used.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs  # noqa: E402

stubs.install()

from tools import registry  # noqa: E402
import agent_tools  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"
    config.cfgAuthToken = ""


def _reply(message, finish="stop"):
    return True, json.dumps({"choices": [{"message": message,
                                          "finish_reason": finish}]}), 200


def test_tool_loop_uses_the_configured_max_tokens(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "agent_max_tokens", 3000)
    seen = {}

    def fake_post(body):
        seen["body"] = json.loads(body)
        return _reply({"content": "ok"})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("hi", None, {}, max_iters=1) == "ok"
    assert seen["body"]["max_tokens"] == 3000


def test_truncated_tool_arguments_are_never_executed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    executed = []
    monkeypatch.setattr(
        agent_tools, "execTool",
        lambda name, args: executed.append((name, args)) or '{"ok":true}')
    seen = {"n": 0, "second": None}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] == 1:
            return _reply({
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "write_file",
                                 "arguments": '{"path":"w.py","content":"print(1'},
                }],
            }, finish="length")
        seen["second"] = json.loads(body)
        return _reply({"content": "I will split it into chunks."})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    reply = llm.callLLMWithTools("make it", None, {}, max_iters=2)

    assert reply == "I will split it into chunks."
    assert executed == []
    tools = [m for m in seen["second"]["messages"] if m.get("role") == "tool"]
    assert tools
    payload = json.loads(tools[0]["content"])
    assert "max_tokens" in payload["error"]
    assert "append=true" in payload["error"]


def test_length_finish_without_content_is_an_explicit_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        llm, "postLLM", lambda body: _reply({"content": ""}, finish="length"))
    reply = llm.callLLMWithTools("x", None, {}, max_iters=1)
    assert reply.startswith("ERROR:")
    assert "max_tokens" in reply


def test_every_requested_tool_runs_and_slow_ones_are_annotated(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        agent_tools, "execTool",
        lambda name, args: calls.append(name) or '{"ok":true}')

    # Two ticks per tool: start 0, end 40000 -> over the 30s advisory budget.
    state = {"n": 0}

    def fake_ticks():
        state["n"] += 1
        return 0 if state["n"] % 2 else 40000

    monkeypatch.setattr(llm, "_ticks_ms", fake_ticks)
    seen = {"n": 0, "second": None}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] == 1:
            return _reply({
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "get_status", "arguments": "{}"}},
                    {"id": "c2", "type": "function",
                     "function": {"name": "get_status", "arguments": "{}"}},
                ],
            }, finish="tool_calls")
        seen["second"] = json.loads(body)
        return _reply({"content": "done"})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("go", None, {}, max_iters=2) == "done"

    # Neither call was skipped by a shared budget.
    assert calls == ["get_status", "get_status"]
    tools = [m for m in seen["second"]["messages"] if m.get("role") == "tool"]
    assert len(tools) == 2
    for msg in tools:
        assert json.loads(msg["content"]).get("slow_tool") is True


def test_agent_loop_gets_a_longer_response_budget(tmp_path, monkeypatch):
    # Generating a multi-KB write_file argument takes far longer than a prose
    # reply. The old fixed 45s read timeout is why the round that had to emit
    # the script always died with ETIMEDOUT, leaving a placeholder on disk.
    _setup(tmp_path, monkeypatch)
    seen = {}

    def fake_raw(url, body, headers, timeout=None, tries=None):
        seen["timeout"] = llm._call_timeout
        seen["tries"] = llm._call_tries
        return _reply({"content": "ok"})

    monkeypatch.setattr(llm, "_post_raw", fake_raw)
    assert llm.callLLMWithTools("hi", None, {}, max_iters=1) == "ok"

    assert seen["timeout"] == llm._LLM_AGENT_TIMEOUT
    assert seen["timeout"] > llm._LLM_TIMEOUT
    # Cleared afterwards: a plain chat reply keeps the short budget.
    assert llm._call_timeout is None and llm._call_tries is None


def test_default_iteration_budget_fits_a_build(tmp_path, monkeypatch):
    # skill_view + web_fetch + write chunks + run_script is ~4 rounds; 3 used
    # to strand the turn mid-build.
    _setup(tmp_path, monkeypatch)
    assert config.DEFAULT_AGENT_MAX_ITERS >= 4
    assert config.agent_max_iters == config.DEFAULT_AGENT_MAX_ITERS
    assert config._clamp_iters(99) == config.AGENT_MAX_ITERS_MAX


def test_workspace_listing_reaches_the_prompt(tmp_path, monkeypatch):
    # "It forgot it already wrote the script": a new turn had no listing, so it
    # re-read the skill and rewrote a placeholder over its own file.
    _setup(tmp_path, monkeypatch)
    import fsutil
    import prompt
    import write_file
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    assert write_file.write("weather_panel.py", "print('x')\n")["success"]
    text = prompt.buildMiniPrompt()
    assert "weather_panel.py" in text


def test_tool_trace_survives_into_the_next_turn(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    p = "opt/data/sessions/t.jsonl"
    agent_tools.appendChatLog("build the panel", "written",
                              path=p, tools="write_file -> 15B placeholder")
    msgs = []
    agent_tools.injectRecentLog(msgs, "try again", path=p)
    notes = [m for m in msgs if m["role"] == "system"]
    assert notes and "write_file -> 15B placeholder" in notes[0]["content"]


def test_request_body_stays_under_the_device_budget(tmp_path, monkeypatch):
    # 25-29KB usually POSTs; 30KB+ starts timing out on the board. The loop
    # must drop old tool results rather than grow without bound.
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_tools, "execTool",
        lambda name, args: '{"content":"' + ("x" * 4000) + '"}')
    sizes = []
    state = {"n": 0}

    def fake_post(body):
        state["n"] += 1
        sizes.append(len(body))
        if state["n"] <= 10:
            return _reply({"content": "", "tool_calls": [
                {"id": "c%d" % state["n"], "type": "function",
                 "function": {"name": "read_file", "arguments": "{}"}}]},
                finish="tool_calls")
        return _reply({"content": "done"})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("go", None, {}, max_iters=11) == "done"
    assert max(sizes) <= llm.BODY_BUDGET


def test_a_dropped_tool_result_says_so(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    msgs = [{"role": "tool", "content": "y" * 5000},
            {"role": "tool", "content": "z" * 5000}]
    req = {"model": "m", "messages": msgs}
    body = llm._encode_request(req, msgs, budget=7000)
    assert len(body) <= 7000
    assert "read the file again" in msgs[0]["content"]
    assert msgs[1]["content"] == "z" * 5000  # newest result kept


def test_repeated_reads_of_the_same_file_are_refused(tmp_path, monkeypatch):
    # The real failure: 14 read_file calls on one script, no write, budget
    # exhausted. Two slices is enough; after that force an edit.
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        agent_tools, "execTool",
        lambda name, args: calls.append(args.get("path")) or '{"ok":true}')
    seen = {"n": 0, "last": None}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] <= 4:
            return _reply({"content": "", "tool_calls": [
                {"id": "c%d" % seen["n"], "type": "function",
                 "function": {"name": "read_file",
                              "arguments": '{"path":"w.py"}'}}]},
                finish="tool_calls")
        seen["last"] = json.loads(body)
        return _reply({"content": "done"})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("go", None, {}, max_iters=5) == "done"

    assert calls == ["w.py", "w.py"]  # only two real reads
    tools = [m for m in seen["last"]["messages"] if m.get("role") == "tool"]
    assert "Stop paging" in tools[-1]["content"]


def test_reads_of_different_files_are_independent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        agent_tools, "execTool",
        lambda name, args: calls.append(args.get("path")) or '{"ok":true}')
    seen = {"n": 0, "last": None}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] <= 4:
            path = "a.py" if seen["n"] % 2 else "b.py"
            return _reply({"content": "", "tool_calls": [
                {"id": "c%d" % seen["n"], "type": "function",
                 "function": {"name": "read_file",
                              "arguments": '{"path":"%s"}' % path}}]},
                finish="tool_calls")
        seen["last"] = json.loads(body)
        return _reply({"content": "done"})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("go", None, {}, max_iters=5) == "done"
    assert calls == ["a.py", "b.py", "a.py", "b.py"]


def test_model_can_build_a_script_in_chunks_and_run_it(tmp_path, monkeypatch):
    # End-to-end through the real tools: two write_file chunks (append), then
    # run_script. This is the workflow the weather dashboard depends on.
    _setup(tmp_path, monkeypatch)
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    seen = {"n": 0, "last": None}

    def call(name, args):
        return {"id": "c%d" % seen["n"], "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] == 1:
            return _reply({"content": "", "tool_calls": [call(
                "write_file",
                {"path": "panel.py",
                 "content": "def main():\n    print('panel ok')\n"})]},
                finish="tool_calls")
        if seen["n"] == 2:
            return _reply({"content": "", "tool_calls": [call(
                "write_file",
                {"path": "panel.py", "append": True,
                 "content": "if __name__ == '__main__':\n    main()\n"})]},
                finish="tool_calls")
        if seen["n"] == 3:
            return _reply({"content": "", "tool_calls": [call(
                "run_script", {"path": "panel.py"})]}, finish="tool_calls")
        seen["last"] = json.loads(body)
        return _reply({"content": "Created and ran panel.py."})

    monkeypatch.setattr(llm, "postLLM", fake_post)
    reply = llm.callLLMWithTools("make a panel", None, {}, max_iters=4)

    assert reply == "Created and ran panel.py."
    tools = [m for m in seen["last"]["messages"] if m.get("role") == "tool"]
    run = json.loads(tools[-1]["content"])
    assert run["success"] is True
    assert "panel ok" in run["output"]
