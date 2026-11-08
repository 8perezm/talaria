# test_esp_deploy.py — pure-helper contract for scripts/esp_deploy.py.
#
# The CLI itself talks to hardware (mpremote / serial), so tests only pin
# the hardware-free mapping, snippet and parsing helpers.  Live behaviour
# (copy + size verify + reset) is exercised against the bench board, not here.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import esp_deploy as ed


def test_remote_for_local_uses_forward_slashes():
    assert ed.remote_for_local("server.py") == "server.py"
    assert ed.remote_for_local(os.path.join("www", "assets", "app.js")) == \
        "www/assets/app.js"
    assert ed.remote_for_local("/www/index.html") == "www/index.html"


def test_parse_spec_defaults_remote_to_repo_relative():
    root = os.path.join("r", "repo")
    local, remote = ed.parse_spec("server.py", root=root)
    assert local == os.path.join(root, "server.py")
    assert remote == "server.py"


def test_parse_spec_explicit_remote():
    root = os.path.join("r", "repo")
    local, remote = ed.parse_spec("a.py:tools/a.py", root=root)
    assert remote == "tools/a.py"
    assert local == os.path.join(root, "a.py")


def test_parse_spec_windows_drive_is_not_a_remote():
    drive_root = "C:\\repo"
    local, remote = ed.parse_spec("C:\\repo\\a.py", root=drive_root)
    assert remote == "a.py"
    assert local == os.path.normpath("C:\\repo\\a.py")


def test_parent_dirs_expands_intermediates_in_order():
    assert ed.parent_dirs(["server.py"]) == []
    assert ed.parent_dirs(["www/assets/app.js"]) == ["www", "www/assets"]
    assert ed.parent_dirs(["tools/a.py", "www/assets/app.js"]) == [
        "tools", "www", "www/assets"]


def test_mkdir_snippet_ignores_existing_dirs():
    code = ed.mkdir_snippet(["www", "www/assets"])
    assert "os.mkdir" in code and "OSError" in code
    assert "www/assets" in code


def test_stat_snippet_tags_every_remote():
    code = ed.stat_snippet(["a.py", "b.py"])
    assert ed.STAT_TAG in code and "a.py" in code and "b.py" in code


def test_parse_stat_output_reads_batched_lines():
    out = "STATSIZE a.py 123\r\nSTATSIZE b.py ERR\r\n>>> "
    assert ed.parse_stat_output(out, ["a.py", "b.py"]) == {
        "a.py": 123, "b.py": None}


def test_parse_stat_output_ignores_echo_noise():
    # File contents echo back over the REPL (e.g. JS `new Error`); only
    # STATSIZE lines count, and only the first per remote.
    out = "new Error('x')\nSTATSIZE a.py 10\nSTATSIZE a.py 99\n"
    assert ed.parse_stat_output(out, ["a.py"]) == {"a.py": 10}


def test_contains_traceback_matches_exactly():
    assert ed.contains_traceback("Traceback (most recent call last)\n  ...")
    assert not ed.contains_traceback("new Error('boom')")
    assert not ed.contains_traceback("")
    assert not ed.contains_traceback(None)
