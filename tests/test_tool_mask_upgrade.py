# test_tool_mask_upgrade.py - new tools must reach boards whose config was
# already saved with a default mask.
#
# Regression: the upgrade rule only matched (1 << k) - 1, so a stored default
# mask that includes a deliberate default-off tool (exec_py) never matched and
# every tool added afterwards stayed disabled forever.
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app"))

import agent_tools  # noqa: E402
import config  # noqa: E402
from tools import registry  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1


def test_saved_default_mask_gains_new_tool(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # exactly what a 22-tool board had on flash: all on except exec_py
    config.saveToolsMask(0x3DFFFF)
    config.loadConfig()
    idx = agent_tools.toolIndex("run_script")
    assert (config.gToolsMask >> idx) & 1 == 1
    # the deliberate default-off bit is preserved
    assert (config.gToolsMask >> agent_tools.toolIndex("exec_py")) & 1 == 0
    assert config.gToolsMask == 0x7DFFFF


def test_customised_mask_is_left_alone(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # user turned something off explicitly: not a default mask, so no upgrade
    config.saveToolsMask(0x3DFFFF & ~(1 << 3))
    config.loadConfig()
    idx = agent_tools.toolIndex("run_script")
    assert (config.gToolsMask >> idx) & 1 == 0
    assert (config.gToolsMask >> 3) & 1 == 0


def test_old_all_on_mask_still_upgrades(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.saveToolsMask((1 << 18) - 1)  # plain all-on, 18 tools
    config.loadConfig()
    assert config.gToolsMask == 0x7FFFFF
