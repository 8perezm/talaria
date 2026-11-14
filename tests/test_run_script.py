# test_run_script.py - the run_script tool and its executor.
#
# The tool is a thin wrapper over cron.run_script_file(), so these cover both:
# the JSON contract the model sees, and that a workspace .py file really runs.
import json
import os
import sys
import types

import cron
import tools.tool_run_script as tool


def _fake_cron(monkeypatch, result):
    mod = types.ModuleType("cron")
    mod.run_script_file = lambda path: result
    monkeypatch.setitem(sys.modules, "cron", mod)


def test_tool_returns_stdout(monkeypatch):
    _fake_cron(monkeypatch, (True, "hello from script"))
    out = json.loads(tool.TOOL["run"]({"path": "hello.py"}))
    assert out == {"success": True, "path": "hello.py",
                   "output": "hello from script"}


def test_tool_reports_executor_error(monkeypatch):
    _fake_cron(monkeypatch, (False, "exec failed: NameError: x"))
    out = json.loads(tool.TOOL["run"]({"path": "broken.py"}))
    assert out["success"] is False
    assert "NameError" in out["error"]


def test_tool_requires_path(monkeypatch):
    out = json.loads(tool.TOOL["run"]({}))
    assert out["success"] is False
    assert "path" in out["error"]


def test_rejects_paths_outside_workspace():
    ok, err = cron.run_script_file("opt/data/cron.json")
    assert ok is False
    assert "workspace" in err


def test_executes_a_workspace_script(tmp_path, monkeypatch):
    import fsutil
    # full() prefixes "/" when _FS_ROOT is empty, so point the tree at tmp
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    os.makedirs(os.path.join(str(tmp_path), "opt", "data", "workspace"),
                exist_ok=True)
    path = os.path.join(str(tmp_path), "opt", "data", "workspace", "hello.py")
    with open(path, "w") as f:
        f.write("print('hi from the device workspace')\n")

    ok, out = cron.run_script_file("hello.py")
    assert ok is True
    assert "hi from the device workspace" in out


def test_missing_script_fails_cleanly(tmp_path, monkeypatch):
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ok, err = cron.run_script_file("does-not-exist.py")
    assert ok is False
    assert isinstance(err, str) and err


def test_runs_as_main_and_captures_stdout(tmp_path, monkeypatch):
    # Generated scripts commonly end in `if __name__ == "__main__": main()`
    # and some libraries write through sys.stdout rather than print().
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "main_style.py"), "w") as f:
        f.write("import sys\n"
                "def main():\n"
                "    print('from main')\n"
                "    sys.stdout.write('via stdout\\n')\n"
                "    print('file=' + __file__)\n"
                "if __name__ == '__main__':\n"
                "    main()\n")

    ok, out = cron.run_script_file("main_style.py")
    assert ok is True
    assert "from main" in out
    assert "via stdout" in out
    assert "/workspace/main_style.py" in out


def test_run_script_releases_the_panel_buffer(tmp_path, monkeypatch):
    # epd.init() leaves the driver holding its display buffers; while they are
    # held every 15KB LLM POST times out until a reboot. run_script must call
    # deinit, and it must find the module by import: the frozen `epd` is NOT
    # in sys.modules, which is why the first version silently did nothing.
    import fsutil
    import types
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "panel.py"), "w") as f:
        f.write("import epd\nepd.init()\nprint('drew')\n")

    calls = []
    fake = types.ModuleType("epd")
    fake.init = lambda: (960, 540)
    fake.deinit = lambda: calls.append("deinit")
    monkeypatch.setitem(sys.modules, "epd", fake)

    ok, out = cron.run_script_file("panel.py")
    assert ok is True and "drew" in out
    assert calls == ["deinit"]


def test_panel_release_imports_epd_when_it_is_not_in_sys_modules(
        tmp_path, monkeypatch):
    # The frozen module is absent from sys.modules; the release path must
    # still reach it.
    import fsutil
    import types
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "plain.py"), "w") as f:
        f.write("print('no panel used')\n")

    calls = []
    fake = types.ModuleType("epd")
    fake.deinit = lambda: calls.append("deinit")
    monkeypatch.setitem(sys.modules, "epd", fake)
    assert "epd" in sys.modules  # the import path is what matters

    ok, out = cron.run_script_file("plain.py")
    assert ok is True
    assert calls == ["deinit"]


def test_run_script_releases_the_panel_after_a_crash(tmp_path, monkeypatch):
    import fsutil
    import types
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "boom.py"), "w") as f:
        f.write("import epd\nepd.init()\nraise ValueError('boom')\n")

    calls = []
    fake = types.ModuleType("epd")
    fake.init = lambda: (960, 540)
    fake.deinit = lambda: calls.append("deinit")
    monkeypatch.setitem(sys.modules, "epd", fake)

    ok, err = cron.run_script_file("boom.py")
    assert ok is False and "boom" in err
    assert calls == ["deinit"]


def test_panel_script_is_refused_when_memory_is_exhausted(tmp_path, monkeypatch):
    # A third epd.init() in one boot hard-faults the board. Refuse with a
    # message the model can act on instead of taking the server down.
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "panel.py"), "w") as f:
        f.write("import epd\nepd.init()\nprint('drew')\n")
    monkeypatch.setattr(cron, "PANEL_MIN_FREE", 10 ** 9)
    import gc
    monkeypatch.setattr(gc, "mem_free", lambda: 1000, raising=False)
    ok, err = cron.run_script_file("panel.py")
    assert ok is False
    assert "panel memory" in err and "reboot" in err.lower()


def test_non_panel_scripts_ignore_the_panel_budget(tmp_path, monkeypatch):
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ws = os.path.join(str(tmp_path), "opt", "data", "workspace")
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "plain.py"), "w") as f:
        f.write("print('no panel')\n")
    monkeypatch.setattr(cron, "PANEL_MIN_FREE", 10 ** 9)
    ok, out = cron.run_script_file("plain.py")
    assert ok is True and "no panel" in out


def test_appended_chunks_form_a_runnable_script(tmp_path, monkeypatch):
    import fsutil
    import write_file
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    assert write_file.write(
        "chunked.py", "def main():\n    print('chunked ok')\n")["success"]
    assert write_file.write(
        "chunked.py", "if __name__ == '__main__':\n    main()\n",
        append=True)["success"]
    ok, out = cron.run_script_file("chunked.py")
    assert ok is True and "chunked ok" in out
