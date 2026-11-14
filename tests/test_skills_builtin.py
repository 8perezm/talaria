# test_skills_builtin.py — firmware-shipped skills (the screen guide).
#
# The agent should not have to spend tool rounds rediscovering /app/screen.py
# and /app/epd.py on every board. ensure_builtin() seeds the guide once per
# build, never overwrites a user copy and leaves a deleted one deleted.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs  # noqa: E402

stubs.install()

import builtin_skills  # noqa: E402
import skillstore  # noqa: E402


def test_screen_skill_satisfies_the_store_contract():
    content = builtin_skills.SKILLS["screen"]
    assert len(content.encode("utf-8")) <= skillstore.SKILL_MAX_BYTES
    desc, err = skillstore.parse_desc(content)
    assert err == "" and desc
    assert skillstore.scan(content) is None
    assert skillstore.section_warnings(content) == []
    # The calls that actually exist on the device are documented.
    for mark in ("epd.init", "epd.update", "paneltext", "size=",
                "run_script", "append=true"):
        assert mark in content, mark


def test_ensure_builtin_installs_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installed = skillstore.ensure_builtin()
    assert installed == ["screen"]
    view = skillstore.view("screen")
    assert view["success"] is True
    assert "epd.update" in view["content"]
    marker = open(os.path.join("opt", "data", "skills", ".builtin")).read()
    state = skillstore.json.loads(marker)
    assert state["v"] == str(builtin_skills.BUILTIN_VERSION)
    assert "screen" in state["h"]
    # Second boot of the same build is a no-op.
    assert skillstore.ensure_builtin() == []


def _bump(monkeypatch, version):
    monkeypatch.setattr(builtin_skills, "BUILTIN_VERSION", version)


def test_a_version_bump_replaces_an_untouched_builtin(tmp_path, monkeypatch):
    # The bug this pins: the marker advanced to the new version while the
    # existing file was skipped as "a user copy", so a revised guide could
    # never ship.
    monkeypatch.chdir(tmp_path)
    assert skillstore.ensure_builtin() == ["screen"]
    monkeypatch.setitem(builtin_skills.SKILLS, "screen",
                        builtin_skills.SKILLS["screen"] + "\n<!-- v2 -->\n")
    _bump(monkeypatch, 99)
    assert skillstore.ensure_builtin() == ["screen"]
    assert "v2" in skillstore.view("screen")["content"]


def test_an_edited_builtin_survives_a_version_bump(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert skillstore.ensure_builtin() == ["screen"]
    p = os.path.join("opt", "data", "skills", "screen.md")
    with open(p, "a") as f:
        f.write("\nmy own note\n")
    _bump(monkeypatch, 99)
    assert skillstore.ensure_builtin() == []
    assert "my own note" in skillstore.view("screen")["content"]


def test_a_legacy_bare_version_marker_migrates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(os.path.join("opt", "data", "skills"))
    with open(os.path.join("opt", "data", "skills", "screen.md"), "w") as f:
        f.write("// desc: old shipped copy\n# Old\n\nWhen to use: x.\n\n"
                "Procedure: x.\n\nPitfalls: x.\n\nVerification: x.\n")
    with open(os.path.join("opt", "data", "skills", ".builtin"), "w") as f:
        f.write("1")
    assert skillstore.ensure_builtin() == ["screen"]
    assert "epd.update" in skillstore.view("screen")["content"]


def test_a_legacy_marker_without_the_file_reinstalls(tmp_path, monkeypatch):
    # Real board state after a botched bump: the marker already claims the new
    # version but the file was skipped. The banner then said "installed", yet
    # /api/skills was empty forever.
    monkeypatch.chdir(tmp_path)
    os.makedirs(os.path.join("opt", "data", "skills"))
    with open(os.path.join("opt", "data", "skills", ".builtin"), "w") as f:
        f.write(str(builtin_skills.BUILTIN_VERSION))
    assert skillstore.ensure_builtin() == ["screen"]
    assert skillstore.view("screen")["success"] is True


def test_user_copy_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(os.path.join("opt", "data", "skills"))
    with open(os.path.join("opt", "data", "skills", "screen.md"), "w") as f:
        f.write("// desc: my own screen notes\n# Mine\n\n"
                "When to use: never.\n\nProcedure: none.\n\n"
                "Pitfalls: none.\n\nVerification: none.\n")
    assert skillstore.ensure_builtin() == []
    assert "my own screen notes" in skillstore.view("screen")["content"]


def test_deleted_builtin_stays_deleted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert skillstore.ensure_builtin() == ["screen"]
    os.remove(os.path.join("opt", "data", "skills", "screen.md"))
    assert skillstore.ensure_builtin() == []
    assert skillstore.view("screen")["success"] is False
    # ...until the next build ships a revision.
    _bump(monkeypatch, 99)
    assert skillstore.ensure_builtin() == ["screen"]


def test_boot_installs_the_screen_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import agent_tools
    agent_tools.initAgentFS()
    assert skillstore.view("screen")["success"] is True


def test_screen_skill_reaches_the_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import prompt
    skillstore.ensure_builtin()
    text = prompt.buildMiniPrompt()
    assert "screen" in text
    assert "epd" in text
