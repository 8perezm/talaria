# test_mini_phase7.py — Phase 7: file tools + checkpoints.
# _FS_ROOT override pattern reused from tests/test_files.py (set on BOTH
# server and fsutil: server wrappers pass server._FS_ROOT explicitly while
# checkpoint + the tool modules use fsutil._FS_ROOT). No device contact.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import pytest

import agent_tools
import checkpoint
import config
import fsutil
import patch_file
import prompt
import read_file
import search_files
import server
import write_file
from tools import registry


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path))
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"
    config.cfgAuthToken = ""
    import net
    net.apMode = False
    monkeypatch.setattr(net, "is_connected", lambda: True)
    server._app = None


def _request(method, path, payload=None, raw=None, ctype=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        if method == "get":
            return await client.get(path)
        headers = {}
        body = None
        if raw is not None:
            body = raw
            headers["Content-Type"] = ctype
        elif payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        return await getattr(client, method)(path, headers=headers, body=body)

    return asyncio.run(_do())


def _multipart(field, filename, data, boundary="BOUND7"):
    out = b"--" + boundary.encode() + b"\r\n"
    out += ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
            % (field, filename)).encode()
    out += b"Content-Type: application/octet-stream\r\n\r\n"
    out += data + b"\r\n--" + boundary.encode() + b"--\r\n"
    return out, "multipart/form-data; boundary=" + boundary


def test_files_locked_to_data_home(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write("server.py", "SYSTEM")
    res = _request("get", "/api/files")
    assert res.status_code == 200, res.status_code
    assert res.json["path"] == "/opt/data"
    assert res.json["parent"] is None
    # /server.py through Files means opt/data/server.py, never flash server.py.
    res = _request("get", "/api/files/content?path=/server.py")
    assert res.status_code == 404, res.status_code
    res = _request("post", "/api/files/save",
                   {"path": "/server.py", "content": "DATA"})
    assert res.status_code == 200, res.status_code
    assert res.json["path"] == "/opt/data/server.py"
    assert _read("server.py") == b"SYSTEM"
    assert _read("opt/data/server.py") == b"DATA"


def test_system_hatch_reaches_flash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write("server.py", "SYSTEM")
    res = _request("get", "/api/system/files")
    assert res.status_code == 200, res.status_code
    assert res.json["path"] == "/"
    assert any(e["name"] == "server.py" for e in res.json["entries"])
    res = _request("get", "/api/system/files/content?path=/server.py")
    assert res.status_code == 200, res.status_code
    assert res.json["content"] == "SYSTEM"
    res = _request("post", "/api/system/files/save",
                   {"path": "/note.txt", "content": "hello"})
    assert res.status_code == 200 and res.json["path"] == "/note.txt"


def _write(rel, data):
    with open(os.path.join(str(fsutil._FS_ROOT), rel), "wb") as f:
        if isinstance(data, str):
            data = data.encode("utf-8")
        f.write(data)


def _read(rel):
    with open(os.path.join(str(fsutil._FS_ROOT), rel), "rb") as f:
        return f.read()


# ---- slots 19-23 ----

def test_slots_19_22_order(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert names[18:23] == ["read_file", "write_file", "patch_file",
                            "search_files", "run_script"]
    assert names.index("read_file") == 18  # slot 19 (1-based)
    assert names.index("write_file") == 19  # slot 20
    assert names.index("patch_file") == 20  # slot 21
    assert names.index("search_files") == 21  # slot 22
    assert names.index("run_script") == 22  # slot 23
    assert len(names) == 23
    assert agent_tools.all_tools_mask() == 0x7FFFFF


def test_new_tools_default_on_and_upgrade(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        os.remove("config.json")
    except OSError:
        pass
    config.loadConfig()
    for nm in ("read_file", "write_file", "patch_file", "search_files"):
        assert (config.gToolsMask >> agent_tools.toolIndex(nm)) & 1 == 1
    assert config.gToolsMask == 0x7DFFFF  # all 23 on except exec_py
    config.saveToolsMask(0x3FFFF)  # old 18-tool "all on" (exec_py on)
    config.loadConfig()
    assert config.gToolsMask == 0x7FFFFF  # gains 5, deliberate exec_py kept
    config.saveToolsMask(0x1FFFF)  # old 17-tool "all on" (exec_py off)
    config.loadConfig()
    assert config.gToolsMask == 0x7DFFFF  # gains the new tools, NOT exec_py


# ---- read_file slices ----

def test_read_slice_offsets(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert fsutil.write_text("alpha.txt", "0123456789ABCDEF") == ""
    r = read_file.read("alpha.txt", 0, 4)
    assert r["success"] and r["content"] == "0123"
    assert r["size"] == 16 and r["truncated"] is True
    r = read_file.read("alpha.txt", 4, 4)
    assert r["content"] == "4567" and r["truncated"] is True
    r = read_file.read("alpha.txt", 14, 10)
    assert r["content"] == "EF" and r["truncated"] is True  # offset>0 flags
    r = read_file.read("alpha.txt", 0, 100)
    assert r["content"] == "0123456789ABCDEF" and r["truncated"] is False
    r = read_file.read("alpha.txt", 16, 10)
    assert r["content"] == "" and r["truncated"] is True  # at EOF, before!=0
    r = read_file.read("alpha.txt", 99, 10)
    assert r["content"] == "" and r["truncated"] is True  # past EOF
    assert read_file.read("alpha.txt", -1, 4)["success"] is False
    assert read_file.read("alpha.txt", 0, 0)["success"] is False
    r = read_file.read("alpha.txt")  # defaults offset=0 limit=2048
    assert r["success"] and r["limit"] == 2048
    r = read_file.read("alpha.txt", 0, 99999)  # clamped to 4096
    assert r["success"] and r["limit"] == 4096
    assert read_file.read("missing.txt")["success"] is False
    assert read_file.read("../evil")["success"] is False  # root jail
    s = agent_tools.execTool("read_file", {"path": "alpha.txt",
                                           "offset": 0, "limit": 4})
    assert json.loads(s)["content"] == "0123"


def test_read_refusals_and_types(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write("config.json", '{"api_key": "SECRET"}')
    _write("tg.json", '{"bot_token": "SECRET"}')
    _write("half.tmp", "partial")
    _write("note.txt.bak", "old snapshot")
    _write("blob.bin", bytes([0xFF, 0xFE, 0x00, 0x41]))
    os.mkdir("adir")
    r = read_file.read("config.json")
    assert r["success"] is False and "secret" in r["error"].lower()
    r = read_file.read("tg.json")
    assert r["success"] is False and "secret" in r["error"].lower()
    assert read_file.read("half.tmp")["success"] is False
    r = read_file.read("note.txt.bak")  # .bak IS readable (inspection)
    assert r["success"] and r["content"] == "old snapshot"
    r = read_file.read("blob.bin")
    assert r["success"] is False and "binary" in r["error"]
    assert read_file.read("adir")["success"] is False


# ---- write_file ----

_WRITE_REFUSED = ("config.json", "memory.txt", "user.txt", "chatlog.jsonl",
                  "chatlog.prev.jsonl", "cron.json", "tg.json",
                  "bundles.json", "pending_mem.json", "pending_x.json",
                  "skills/evil.md", "pending_skills/x.json", "side.bak",
                  "side.tmp")


def test_write_checkpoint_then_refusals(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = write_file.write("n.txt", "hi")
    assert r["success"] and r["size"] == 2 and r["backed_up"] is False
    assert _read("n.txt") == b"hi"
    r = write_file.write("n.txt", "hi2")
    assert r["success"] and r["backed_up"] is True
    assert _read("n.txt.bak") == b"hi"  # .bak holds the previous content
    assert write_file.write("big.txt", "x" * 4097)["success"] is False
    assert write_file.write("big.txt", "x" * 4096)["success"] is True
    for p in _WRITE_REFUSED:
        r = write_file.write(p, "x")
        assert r["success"] is False, p
    assert write_file.write("../evil", "x")["success"] is False
    assert write_file.write("empty.txt", "")["success"] is False
    s = agent_tools.execTool("write_file", {"path": "t.txt",
                                            "content": "via tool"})
    assert json.loads(s)["success"] is True


def test_write_skills_refusal_points_at_flow(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = write_file.write("skills/evil.md", "x")
    assert r["success"] is False
    assert "skill_view" in r["error"] and "/api/skills" in r["error"]
    r = write_file.write("memory.txt", "x")
    assert r["success"] is False and "memory tool" in r["error"]
    r = write_file.write("cron.json", "x")
    assert r["success"] is False and "cron" in r["error"]


# ---- patch_file ----

def test_patch_unique_ambiguous(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert fsutil.write_text("p.txt", "aaa bbb aaa") == ""
    r = patch_file.patch("p.txt", "bbb", "ccc")
    assert r["success"] and r["backed_up"] is True
    assert _read("p.txt") == b"aaa ccc aaa"
    assert _read("p.txt.bak") == b"aaa bbb aaa"
    r = patch_file.patch("p.txt", "aaa", "zzz")  # twice: ambiguous
    assert r["success"] is False and "2 times" in r["error"]
    assert _read("p.txt") == b"aaa ccc aaa"  # untouched, no new .bak write
    r = patch_file.patch("p.txt", "nope", "zzz")
    assert r["success"] is False and "No match" in r["error"]
    r = patch_file.patch("p.txt", "ccc", "ccc")  # no-op
    assert r["success"] is False and "no-op" in r["error"].lower()
    assert patch_file.patch("p.txt", "", "zzz")["success"] is False
    assert patch_file.patch("p.txt", "ccc", "")["success"] is False
    assert patch_file.patch("missing.txt", "a", "b")["success"] is False
    for p in ("config.json", "skills/a.md", "chatlog.jsonl", "cron.json",
              "memory.txt", "tg.json"):
        assert patch_file.patch(p, "a", "b")["success"] is False, p
    s = agent_tools.execTool("patch_file", {"path": "p.txt", "old": "ccc",
                                            "new": "ddd"})
    assert json.loads(s)["success"] is True


def test_patch_size_caps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write("fat.txt", "y" * 5000)
    r = patch_file.patch("fat.txt", "y", "z")
    assert r["success"] is False and "too large" in r["error"]
    assert fsutil.write_text("edge.txt", "a" + "b" * 4094) == ""  # 4095B
    r = patch_file.patch("edge.txt", "a", "ac")  # -> 4096B: fits exactly
    assert r["success"] is True and r["size"] == 4096
    r = patch_file.patch("edge.txt", "ac", "acd")  # -> 4097B: refused
    assert r["success"] is False and "too large" in r["error"]


# ---- checkpoint rotation + rollback ----

def test_bak_rotation_evicts_oldest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert checkpoint.MAX_BACKUPS == 8
    base = 1000000
    for i in range(1, 9):
        assert fsutil.write_text("f%d.txt" % i, "v%d" % i) == ""
        r = checkpoint.backup("f%d.txt" % i)
        assert r["success"] and r["backed_up"] is True
        os.utime(os.path.join(str(tmp_path), "f%d.txt.bak" % i),
                 (base + i, base + i))
    assert checkpoint.list_backups()["count"] == 8
    assert fsutil.write_text("f9.txt", "v9") == ""
    r = checkpoint.backup("f9.txt")
    assert r["success"] and r["backed_up"] is True
    assert r["evicted"] == ["/f1.txt.bak"]  # oldest by mtime goes
    assert not os.path.exists(os.path.join(str(tmp_path), "f1.txt.bak"))
    assert checkpoint.list_backups()["count"] == 8
    names = sorted(b["path"] for b in checkpoint.list_backups()["backups"])
    assert names[0] == "/f2.txt.bak" and names[-1] == "/f9.txt.bak"


def test_backup_missing_and_sidecars(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = checkpoint.backup("new.txt")  # nothing to snap: still success
    assert r["success"] is True and r["backed_up"] is False
    assert checkpoint.backup("../evil")["success"] is False
    assert checkpoint.backup("x.bak")["success"] is False
    assert checkpoint.backup("x.tmp")["success"] is False
    assert checkpoint.backup("config.json")["success"] is False  # managed


def test_rollback_restores_and_refuses(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert fsutil.write_text("r.txt", "v1") == ""
    assert checkpoint.backup("r.txt")["backed_up"] is True
    assert fsutil.write_text("r.txt", "v2") == ""
    r = checkpoint.rollback("r.txt")
    assert r["success"] is True and _read("r.txt") == b"v1"
    assert checkpoint.rollback("nobak.txt")["success"] is False
    assert "no backup" in checkpoint.rollback("nobak.txt")["error"]
    _write("config.json", "{}")
    _write("config.json.bak", "{}")
    assert checkpoint.rollback("config.json")["success"] is False  # managed
    lb = checkpoint.list_backups()
    assert lb["success"] and lb["count"] >= 1
    assert lb["max_backups"] == 8
    assert all(b["path"].endswith(".bak") for b in lb["backups"])


# ---- server: save/upload create .bak; /api/rollback ----

def test_server_save_creates_bak(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("post", "/api/files/save",
                   {"path": "/note.txt", "content": "one"})
    assert res.status_code == 200 and res.json["ok"] is True
    assert res.json["path"] == "/opt/data/note.txt"
    res = _request("post", "/api/files/save",
                   {"path": "/note.txt", "content": "two"})
    assert res.status_code == 200
    res = _request("get", "/api/files/content?path=/note.txt.bak")
    assert res.status_code == 200 and res.json["content"] == "one"
    res = _request("get", "/api/files/content?path=/note.txt")
    assert res.json["content"] == "two"


def test_server_upload_creates_bak(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("post", "/api/files/save",
                   {"path": "/up.txt", "content": "v1"})
    assert res.status_code == 200
    body, ctype = _multipart("file", "up.txt", b"v2")
    res = _request("post", "/api/files/upload?path=/", raw=body, ctype=ctype)
    assert res.status_code == 200 and res.json["ok"] is True
    assert res.json["saved"] == ["/opt/data/up.txt"]
    res = _request("get", "/api/files/content?path=/up.txt.bak")
    assert res.status_code == 200 and res.json["content"] == "v1"


def test_api_rollback_list_and_restore(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("get", "/api/rollback")
    assert res.status_code == 200 and res.json["backups"] == []
    _request("post", "/api/files/save", {"path": "/rb.txt", "content": "one"})
    _request("post", "/api/files/save", {"path": "/rb.txt", "content": "two"})
    res = _request("get", "/api/rollback")
    assert res.status_code == 200 and res.json["count"] == 1
    assert res.json["backups"][0]["path"] == "/opt/data/rb.txt.bak"
    res = _request("post", "/api/rollback", {"path": "/opt/data/rb.txt"})
    assert res.status_code == 200 and res.json["ok"] is True
    res = _request("get", "/api/files/content?path=/rb.txt")
    assert res.json["content"] == "one"
    res = _request("post", "/api/rollback", {"path": "/nobak.txt"})
    assert res.status_code == 404
    res = _request("post", "/api/rollback", {"path": "/config.json"})
    assert res.status_code == 400
    res = _request("post", "/api/rollback", {"nope": 1})
    assert res.status_code == 400


def test_update_blocks_bak(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    body, ctype = _multipart("firmware", "evil.py.bak", b"print(1)")
    res = _request("post", "/update", raw=body, ctype=ctype)
    assert res.status_code == 400
    assert "no acceptable files" in res.json["error"]
    assert not os.path.exists(os.path.join(str(tmp_path), "evil.py.bak"))


# ---- search_files ----

def test_search_hits_caps_binary_jail(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert fsutil.write_text("a/x.py", "hello world\nfoo bar\n") == ""
    assert fsutil.write_text("a/y.txt", "nothing\nhELLO again\n") == ""
    assert fsutil.write_text("sub/z.py", "hello down here\n") == ""
    _write("blob.bin", bytes([0x68, 0x65, 0x6C, 0x6C, 0x6F, 0x00, 0xFF]))
    r = search_files.search("hello")
    assert r["success"] is True and r["root"] == "/"
    got = sorted((m["file"], m["line"]) for m in r["matches"])
    assert ("/a/x.py", 1) in got  # case-insensitive: y.txt line 2 too
    assert ("/a/y.txt", 2) in got and ("/sub/z.py", 1) in got
    assert all("file" in m and "line" in m and "text" in m for m in r["matches"])
    assert not any(m["file"] == "/blob.bin" for m in r["matches"])  # binary
    r = search_files.search("hello", "a")  # root jail: sub/ excluded
    assert r["success"] and r["root"] == "/a"
    assert all(m["file"].startswith("/a/") for m in r["matches"])
    assert r["count"] == 2
    assert search_files.search("")["success"] is False
    assert search_files.search("x" * 121)["success"] is False
    assert search_files.search("hello", "../")["success"] is False
    assert search_files.search("hello", "/missing")["success"] is False
    s = agent_tools.execTool("search_files", {"pattern": "foo"})
    d = json.loads(s)
    assert d["success"] and d["matches"][0]["file"] == "/a/x.py"


def test_search_hit_cap_and_oversize_skip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.mkdir("many")
    for i in range(25):
        assert fsutil.write_text("many/f%02d.txt" % i, "needle %d\n" % i) == ""
    _write("huge.txt", "needle\n" + "x" * 40000)  # over 32KB: skipped
    r = search_files.search("needle")
    assert r["success"] and r["count"] == 20 and r["truncated"] is True
    assert not any(m["file"] == "/huge.txt" for m in r["matches"])
    r = search_files.search("needle", "many/f00.txt")  # file as root: scan it
    assert r["success"] and r["count"] == 1


# ---- prompt ----

def test_prompt_mentions_file_tools_bounded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    p = prompt.buildMiniPrompt()
    assert "read_file" in p and "patch_file" in p
    assert "search_files" in p and "write_file" in p
    assert len(p) < 6000  # total prompt must not grow unbounded


# ---- delegation parity (server wrappers share fsutil) ----

def test_server_wrappers_share_fsutil(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert server._fs_norm("a/./b") == fsutil.norm("a/./b") == "a/b"
    assert server._fs_full("x") == fsutil.full("x", str(tmp_path))
    assert server._fs_write_text("w/t.txt", "hi") == ""
    res, err, _ = server._fs_read_text("w/t.txt")
    assert err == "" and res["content"] == "hi"
    assert server._fs_delete("w") == ""


# ---- micropython portability ----

def test_no_regex_or_bad_codecs_in_new_code():
    base = os.path.join(os.path.dirname(__file__), "..")
    for rel in (os.path.join("app", "fsutil.py"), os.path.join("app", "checkpoint.py"),
                os.path.join("app", "read_file.py"), os.path.join("app", "write_file.py"),
                os.path.join("app", "patch_file.py"), os.path.join("app", "search_files.py")):
        src = open(os.path.join(base, rel), encoding="utf-8").read()
        assert "import re" not in src, "no `re` in %s" % rel
        for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
            assert codec not in src, "unsupported codec in %s" % rel
