import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import server


def test_fs_norm():
    assert server._fs_norm(None) == ""
    assert server._fs_norm("") == ""
    assert server._fs_norm("/") == ""
    assert server._fs_norm("a/b") == "a/b"
    assert server._fs_norm("/a/b/") == "a/b"
    assert server._fs_norm("a//b") == "a/b"
    assert server._fs_norm("a/./b") == "a/b"
    assert server._fs_norm("a\\b") == "a/b"
    assert server._fs_norm("  /tools/x.py  ") == "tools/x.py"
    assert server._fs_norm("..") is None
    assert server._fs_norm("a/../b") is None
    assert server._fs_norm("../a") is None
    assert server._fs_norm("a/" + "x" * 300) is None


def test_fs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    assert server._fs_norm("") == ""
    # write nested (mkdir -p parents)
    assert server._fs_write_text("www/note.txt", "hello") == ""
    # list root shows the dir
    entries, err = server._fs_list_dir("")
    assert err == ""
    assert any(e["name"] == "www" and e["is_dir"] for e in entries)
    entries, err = server._fs_list_dir("www")
    assert err == ""
    assert entries[0]["name"] == "note.txt"
    assert entries[0]["path"] == "/www/note.txt"
    assert entries[0]["size"] == 5
    # read back
    res, err, size = server._fs_read_text("www/note.txt")
    assert err == ""
    assert res["content"] == "hello"
    assert res["truncated"] is False
    # binary read refused
    with open(str(tmp_path / "blob.bin"), "wb") as f:
        f.write(bytes([0xFF, 0xFE, 0x00, 0x01]))
    res, err, size = server._fs_read_text("blob.bin")
    assert res is None
    assert "binary" in err
    # rename
    import os as _os

    src, dst = "www/note.txt", "www/renamed.txt"
    assert server._fs_is_dir(server._fs_full(src)) is False
    _os.rename(server._fs_full(src), server._fs_full(dst))
    res, err, _ = server._fs_read_text("www/renamed.txt")
    assert err == "" and res["content"] == "hello"
    # refusal cases
    assert server._fs_delete("") != ""
    assert server._fs_write_text("", "x") != ""
    assert server._fs_write_text("big.txt", "x" * (server._FS_MAX_WRITE + 1)) != ""
    # recursive delete of tree
    assert server._fs_write_text("d/a.txt", "a") == ""
    assert server._fs_write_text("d/sub/b.txt", "b") == ""
    assert server._fs_delete("d") == ""
    entries, err = server._fs_list_dir("")
    assert err == ""
    assert not any(e["name"] == "d" for e in entries)


def test_fs_list_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    entries, err = server._fs_list_dir("nope")
    assert entries is None
    assert err == "not found"
