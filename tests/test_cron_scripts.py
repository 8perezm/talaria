# test_cron_scripts.py — cron workspace-script jobs (Hermes no_agent parity).
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import cron
import fsutil
import prompt
from tools import registry


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # fsutil file access (script reads) resolves under _FS_ROOT on host;
    # cron.json/chatlog state uses CWD-relative paths (device style).
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path))
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"
    config.cfgAuthToken = ""
    os.makedirs("opt/data/workspace", exist_ok=True)


def _write_script(rel, body):
    with open(os.path.join("opt/data/workspace", rel), "w") as f:
        f.write(body)


def _job(**kw):
    d = {"id": "j1", "prompt": "say hi", "every_s": 3600, "next_run": 5000,
         "enabled": True, "deliver": "log", "webhook_url": "",
         "skills": [], "script": "", "no_agent": False, "created": 1000}
    d.update(kw)
    return d


def _log_lines():
    try:
        with open("opt/data/activity.jsonl") as f:
            return [ln for ln in f if ln.strip()]
    except OSError:
        return []


# ---- path normalisation ----

def test_norm_script_variants(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ws = "opt/data/workspace"
    assert cron._norm_script("hello.py") == ws + "/hello.py"
    assert cron._norm_script("workspace/a.py") == ws + "/a.py"
    assert cron._norm_script("/workspace/a.py") == ws + "/a.py"
    assert cron._norm_script("opt/data/workspace/a.py") == ws + "/a.py"
    assert cron._norm_script("/opt/data/workspace/a.py") == ws + "/a.py"
    assert cron._norm_script("") == ""
    assert cron._norm_script(None) == ""
    assert cron._norm_script("server.py") == ws + "/server.py"  # bare = workspace
    assert cron._norm_script("jobs/daily.py") == ws + "/jobs/daily.py"
    assert cron._norm_script("../evil") is None  # jail break refused
    assert cron._norm_script("opt/data/cron.json") is None  # managed data
    assert cron._norm_script("opt/data/workspace") is None  # the dir itself
    assert cron._norm_script("workspace") is None  # the dir itself
    assert cron._script_display(ws + "/a.py") == "/workspace/a.py"


# ---- add / edit validation ----

def test_add_validation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert cron.add("", 300)["success"] is False  # prompt still required alone
    r = cron.add("ok", 300, script="../evil")
    assert r["success"] is False  # jail break refused
    r = cron.add("ok", 300, script="opt/data/cron.json")
    assert r["success"] is False  # managed data refused
    r = cron.add("ok", 300, no_agent=True)
    assert r["success"] is False  # script-only needs a script
    r = cron.add("", 300, script="workspace/hi.py", no_agent=True)
    assert r["success"] is True  # prompt optional for script-only
    assert r["job"]["script"] == "opt/data/workspace/hi.py"
    assert r["job"]["no_agent"] is True
    assert cron.add("", 300, script="x", no_agent="yes")["success"] is True
    assert cron.list_jobs()["count"] == 2


def test_add_prompt_job_with_script(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.add("check sensors", 300, script="workspace/s.py")
    assert r["success"] is True
    assert r["job"]["script"] == "opt/data/workspace/s.py"
    assert r["job"]["no_agent"] is False
    assert r["job"]["prompt"] == "check sensors"


def test_edit_script_and_clear(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cron.add("check sensors", 300, now=1000)
    r = cron.edit("j1", script="workspace/s.py", no_agent=True)
    assert r["success"] is True
    assert r["job"]["script"] == "opt/data/workspace/s.py"
    assert r["job"]["no_agent"] is True
    assert cron.edit("j1", script="../evil")["success"] is False  # still jailed
    r = cron.edit("j1", script="")  # "" clears...
    assert r["success"] is False  # ...but prompt+no_agent+script all empty now
    r = cron.edit("j1", script="", no_agent=False, prompt="back")
    assert r["success"] is True and r["job"]["script"] == ""


def test_edit_prompt_clear_rules(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cron.add("check sensors", 300, now=1000)
    # agent mode, no script: blanking the prompt is refused
    assert cron.edit("j1", prompt="")["success"] is False
    # script-only job: blank prompt is fine
    cron.edit("j1", script="workspace/s.py", no_agent=True)
    assert cron.edit("j1", prompt="")["success"] is True


# ---- runs ----

def test_run_no_agent_delivers_stdout(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_script("hello.py", 'print("hi from script")\nprint("line2")')
    before = len(_log_lines())
    calls = []

    def _boom(p):
        calls.append(p)
        raise AssertionError("agent must not run in no_agent mode")

    r = cron.run_job(_job(prompt="", script="opt/data/workspace/hello.py",
                          no_agent=True), _boom)
    assert r["success"] is True
    assert calls == []
    assert r["reply"] == "hi from script\nline2"
    assert r["script"] == "/workspace/hello.py" and r["no_agent"] is True
    assert len(_log_lines()) - before == 2
    assert "hello.py" in _log_lines()[-2]


def test_run_agent_mode_prepends_script_output(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_script("s.py", 'print("sensor=42")')
    seen = []
    r = cron.run_job(_job(prompt="report", script="workspace/s.py"),
                     lambda p: seen.append(p) or "reported")
    assert r["success"] is True and r["reply"] == "reported"
    assert "sensor=42" in seen[0] and "Script /workspace/s.py output:" in seen[0]
    assert seen[0].endswith("report")


def test_run_missing_and_failing_scripts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.run_job(_job(prompt="", script="workspace/missing.py",
                          no_agent=True), lambda p: "x")
    assert r["success"] is False and "script" in r["error"]
    _write_script("bad.py", "1/0")
    r = cron.run_job(_job(prompt="", script="workspace/bad.py", no_agent=True),
                     lambda p: "x")
    assert r["success"] is False and "exec failed" in r["error"]
    # agent mode survives a bad script: the turn still runs with a note
    seen = []
    r = cron.run_job(_job(prompt="go", script="workspace/bad.py"),
                     lambda p: seen.append(p) or "ok")
    assert r["success"] is True and "failed" in seen[0]


def test_run_oversize_script_refused(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_script("big.py", 'print("x")\n' + "x" * (cron.SCRIPT_MAX + 10))
    r = cron.run_job(_job(prompt="", script="workspace/big.py", no_agent=True),
                     lambda p: "x")
    assert r["success"] is False and "too large" in r["error"]


def test_old_jobs_without_script_keys_still_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = {"id": "j1", "prompt": "hi", "every_s": 300, "next_run": 1,
              "enabled": True, "deliver": "log", "webhook_url": "",
              "skills": [], "created": 1}
    pub = cron.public(legacy)
    assert pub["script"] == "" and pub["no_agent"] is False
    r = cron.run_job(legacy, lambda p: "legacy ok")
    assert r["success"] is True and r["reply"] == "legacy ok"


def test_tool_dispatch_script(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = agent_tools.execTool("cron", {"op": "add", "prompt": "",
                                      "script": "workspace/hi.py",
                                      "no_agent": True, "every_s": 120})
    d = json.loads(s)
    assert d["success"] is True and d["job"]["no_agent"] is True
    s2 = agent_tools.execTool("cron", {"op": "list"})
    assert json.loads(s2)["jobs"][0]["script"] == "opt/data/workspace/hi.py"


def test_prompt_points_at_workspace(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    p = prompt.buildMiniPrompt()
    assert "opt/data/workspace/" in p
    assert "read_file" in p and "write_file" in p
    assert len(p) < 6000


# ---- name field (Hermes "Name (optional)") ----

def test_name_add_edit_clear(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.add("check plants", 300, name="  Morning check  ")
    assert r["success"] is True and r["job"]["name"] == "Morning check"
    assert cron.list_jobs()["jobs"][0]["name"] == "Morning check"
    assert cron.edit("j1", name="n" * 100)["success"] is True
    assert cron.list_jobs()["jobs"][0]["name"] == "n" * cron.NAME_MAX
    assert cron.edit("j1", name="")["job"]["name"] == ""  # "" clears
    cron.edit("j1", name="kept")
    r = cron.edit("j1", prompt="check plants!")  # None keeps
    assert r["success"] is True and r["job"]["name"] == "kept"


def test_name_optional_and_legacy(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert cron.add("no name", 300)["job"]["name"] == ""
    legacy = {"id": "j1", "prompt": "hi", "every_s": 300, "next_run": 1,
              "enabled": True, "deliver": "log", "webhook_url": "",
              "skills": [], "created": 1}
    assert cron.public(legacy)["name"] == ""
    assert cron.handle({"op": "add", "prompt": "via handle",
                        "name": "handled"})["job"]["name"] == "handled"


def test_tool_dispatch_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = agent_tools.execTool("cron", {"op": "add", "name": "via tool",
                                      "prompt": "x", "every_s": 120})
    assert json.loads(s)["job"]["name"] == "via tool"
