# test_write_append.py — chunked writes and workspace path resolution.
#
# A dashboard-sized script cannot arrive in one completion. write_file now
# accepts append=true (<=4KB per call, <=16KB assembled), and the file tools
# resolve workspace/... and new bare *.py scripts to opt/data/workspace/ so
# run_script finds what write_file wrote.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs  # noqa: E402

stubs.install()

import fsutil  # noqa: E402
import read_file  # noqa: E402
import write_file  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))


def test_bare_script_lands_in_the_workspace(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = write_file.write("weather.py", "print('one')\n")
    assert r["success"] is True
    assert r["path"] == "/opt/data/workspace/weather.py"
    assert os.path.exists(os.path.join(str(tmp_path), "opt", "data",
                                       "workspace", "weather.py"))


def test_workspace_prefix_maps_to_the_data_home(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = write_file.write("workspace/panel.py", "print('panel')\n")
    assert r["success"] is True
    assert r["path"] == "/opt/data/workspace/panel.py"
    # read_file resolves the same bare name to the same file.
    assert read_file.read("panel.py")["content"] == "print('panel')\n"


def test_append_builds_a_script_across_calls(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert write_file.write("weather.py", "print('first')\n")["success"]
    r = write_file.write("weather.py", "print('second')\n", append=True)
    assert r["success"] is True
    assert r["appended"] is True
    assert r["size"] == len("print('first')\nprint('second')\n")
    assert read_file.read("weather.py")["content"] == \
        "print('first')\nprint('second')\n"


def test_per_call_and_assembled_caps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # One call may not exceed the model output budget.
    r = write_file.write("big.py", "x" * (fsutil.TOOL_CONTENT_MAX + 1))
    assert r["success"] is False and "one call" in r["error"]

    # Chunks may assemble up to TOOL_FILE_MAX, and no further.
    chunk = "y" * fsutil.TOOL_CONTENT_MAX
    assert write_file.write("stack.py", chunk)["success"]
    total = fsutil.TOOL_CONTENT_MAX
    while total < fsutil.TOOL_FILE_MAX:
        r = write_file.write("stack.py", chunk, append=True)
        assert r["success"] is True
        total += fsutil.TOOL_CONTENT_MAX
    r = write_file.write("stack.py", "z", append=True)
    assert r["success"] is False
    assert "append cap" in r["error"] or "too large" in r["error"]


def test_existing_root_entry_point_keeps_its_path(tmp_path, monkeypatch):
    # Repairs to main.py/boot.py must not be redirected into the workspace.
    _setup(tmp_path, monkeypatch)
    assert fsutil.write_text("main.py", "old") == ""
    r = write_file.write("main.py", "new")
    assert r["success"] is True
    assert r["path"] == "/main.py"
    assert read_file.read("main.py")["content"] == "new"


def test_append_skips_checkpoint_rotation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert write_file.write("chunks.py", "a\n")["backed_up"] is False
    r = write_file.write("chunks.py", "b\n", append=True)
    assert r["backed_up"] is False
