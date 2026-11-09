# test_verify_fs_image.py — pure-helper contract for the release image check.
import os
import sys


def _mod(name):
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "verify_fs_image.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vfi = _mod("verify_fs_image")


def test_parse_size_first_lines():
    got = vfi.parse_listing("  1341 app/agent_core.py\n  63 app/tools/__init__.py\n")
    assert got == {"app/agent_core.py": 1341, "app/tools/__init__.py": 63}


def test_parse_name_first_lines():
    got = vfi.parse_listing("app/server.py 137319\nwww/index.html 637\n")
    assert got == {"app/server.py": 137319, "www/index.html": 637}


def test_parse_skips_headers_and_dirs():
    text = "name  size\napp/ \n  10 app/a.py\n"
    assert vfi.parse_listing(text) == {"app/a.py": 10}


def test_staging_files_sizes(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_bytes(b"12345")
    (tmp_path / "b.txt").write_bytes(b"xy")
    assert vfi.staging_files(str(tmp_path)) == {"sub/a.py": 5, "b.txt": 2}


def test_main_rejects_unparseable_listing(tmp_path, capsys):
    (tmp_path / "a.py").write_bytes(b"1")
    # sys.executable run with "-l" exits non-zero with usage text: nothing
    # parseable, so main must fail rather than report success.
    rc = vfi.main(["vfi", sys.executable, "img.bin", str(tmp_path)])
    assert rc != 0
