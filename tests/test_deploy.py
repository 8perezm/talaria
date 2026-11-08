# test_deploy.py — deploy.ps1 must ship everything the firmware imports.
#
# The board boots main.py straight from flash, so a module missing from the
# deploy list is not a gradual failure: the device drops to the REPL and the
# dashboard is down. There is no test coverage on the device side, so the list
# is compared against the repo contents here.
import os
import re

PROJ = os.path.join(os.path.dirname(__file__), "..")
DEPLOY = os.path.join(PROJ, "deploy.ps1")

# Host-only modules: executed by CPython (mip install helper), never imported
# on the board.
HOST_ONLY = {"mip_install.py"}


def _deploy_src():
    with open(DEPLOY, encoding="utf-8") as f:
        return f.read()


def _code_list():
    src = _deploy_src()
    block = re.search(r"\$code\s*=\s*@\((.*?)\)", src, re.S)
    assert block, "deploy.ps1 lost its $code list"
    return set(re.findall(r'"([^"]+\.py)"', block.group(1)))


def _ui_list():
    src = _deploy_src()
    block = re.search(r'foreach \(\$f in @\((.*?)\)\)', src, re.S)
    assert block, "deploy.ps1 lost its UI file list"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_deploy_ships_every_root_module():
    on_disk = {f for f in os.listdir(os.path.join(PROJ))
               if f.endswith(".py")} - HOST_ONLY
    missing = on_disk - _code_list()
    assert not missing, "not deployed: %s" % sorted(missing)


def test_deploy_list_has_no_ghosts():
    # A renamed/deleted module left in the list is skipped by Test-Path, but it
    # hides the real gap until the board fails to boot.
    on_disk = {f for f in os.listdir(os.path.join(PROJ)) if f.endswith(".py")}
    ghosts = _code_list() - on_disk
    assert not ghosts, "deploy list points at missing files: %s" % sorted(ghosts)


def test_deploy_ships_the_spa_bundle():
    files = _ui_list()
    assert {"index.html", "favicon.svg", "assets/app.js", "assets/app.css",
            "assets/app.js.gz", "assets/app.css.gz"} <= files
    for name in files:
        assert os.path.exists(os.path.join(PROJ, "www", name)), name


def test_deploy_verifies_sizes_and_resets():
    src = _deploy_src()
    # Copy-Verified is the only thing that catches a truncated mpremote copy.
    assert "function Copy-Verified" in src
    assert "size mismatch" in src
    assert "reset" in src
