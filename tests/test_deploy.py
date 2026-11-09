# test_deploy.py — deploy.ps1 must ship everything the firmware imports.
#
# Layout: only boot.py/main.py live at the filesystem root; the application
# lives in app/ (device: /app, on sys.path via main.py). The board boots
# main.py straight from flash, so a module missing from the deploy list is not
# a gradual failure: the device drops to the REPL and the dashboard is down.
# There is no test coverage on the device side, so the lists are compared
# against the repo contents here.
import os
import re

PROJ = os.path.join(os.path.dirname(__file__), "..")
DEPLOY = os.path.join(PROJ, "deploy.ps1")

# Host-only modules: executed by CPython (mip install helper), never imported
# on the board.
HOST_ONLY = {"mip_install.py"}

# Files that must land at the filesystem root (MicroPython runs them by name).
ROOT_ENTRY_POINTS = {"main.py", "boot.py"}


def _deploy_src():
    with open(DEPLOY, encoding="utf-8") as f:
        return f.read()


def _code_list():
    src = _deploy_src()
    block = re.search(r"\$code\s*=\s*@\((.*?)\)", src, re.S)
    assert block, "deploy.ps1 lost its $code list"
    return set(re.findall(r'"([^"]+\.py)"', block.group(1)))


def _foreach_lists():
    src = _deploy_src()
    return re.findall(r'foreach \(\$f in @\((.*?)\)\)', src, re.S)


def _root_list():
    for block in _foreach_lists():
        items = set(re.findall(r'"([^"]+)"', block))
        if "main.py" in items:
            return items
    raise AssertionError("deploy.ps1 lost its root entry-point list")


def _ui_list():
    for block in _foreach_lists():
        items = set(re.findall(r'"([^"]+)"', block))
        if "index.html" in items:
            return items
    raise AssertionError("deploy.ps1 lost its UI file list")


def test_deploy_ships_every_app_module():
    on_disk = {f for f in os.listdir(os.path.join(PROJ, "app"))
               if f.endswith(".py")} - HOST_ONLY
    missing = on_disk - _code_list()
    assert not missing, "not deployed: %s" % sorted(missing)


def test_deploy_ships_root_entry_points():
    assert ROOT_ENTRY_POINTS <= _root_list()
    for name in _root_list():
        assert os.path.exists(os.path.join(PROJ, name)), name


def test_deploy_list_has_no_ghosts():
    # A renamed/deleted module left in the list is skipped by Test-Path, but it
    # hides the real gap until the board fails to boot.
    app_disk = {f for f in os.listdir(os.path.join(PROJ, "app"))
                if f.endswith(".py")}
    root_disk = {f for f in os.listdir(PROJ) if f.endswith(".py")}
    ghosts = (_code_list() - app_disk) | (_root_list() - root_disk)
    assert not ghosts, "deploy list points at missing files: %s" % sorted(ghosts)


def test_deploy_ships_the_spa_bundle():
    files = _ui_list()
    assert {"index.html", "favicon.svg", "assets/app.js", "assets/app.css",
            "assets/app.js.gz", "assets/app.css.gz"} <= files
    for name in files:
        assert os.path.exists(os.path.join(PROJ, "www", name)), name


def test_deploy_creates_app_dir():
    src = _deploy_src()
    assert "'app'" in src, "deploy.ps1 must mkdir app/ on the device"


def test_deploy_verifies_sizes_and_resets():
    src = _deploy_src()
    # Copy-Verified is the only thing that catches a truncated mpremote copy.
    assert "function Copy-Verified" in src
    assert "size mismatch" in src
    assert "reset" in src
