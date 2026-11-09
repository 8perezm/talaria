# test_verify_fs_image.py — pure-helper contract for the release image check.
#
# The script mounts the image with littlefs-python (same format family the
# board reads) instead of parsing `mklittlefs -l`, whose display mangles
# nested paths. Helpers are tested here against a fake fs, so these tests
# need no littlefs install.
import io
import os


def _mod(name):
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "verify_fs_image.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vfi = _mod("verify_fs_image")


class _Stat:
    def __init__(self, name, kind, size=0):
        self.name = name
        self.type = kind
        self.size = size


class FakeFS:
    """In-memory scandir/stat/open stand-in: {rel path: bytes}."""

    def __init__(self, tree):
        self.tree = dict(tree)

    def _children(self, dirpath):
        seen = {}
        prefix = (dirpath.strip("/") + "/") if dirpath.strip("/") else ""
        for path in self.tree:
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            head = rest.split("/", 1)[0]
            if "/" in rest:
                seen[head] = 2
            else:
                seen[head] = 1
        return seen

    def scandir(self, path):
        norm = path.strip("/") if path != "/" else ""
        return [_Stat(n, k) for n, k in sorted(self._children(norm).items())]

    def stat(self, path):
        rel = path.strip("/")
        if rel in self.tree:
            return _Stat(rel.split("/")[-1], 1, len(self.tree[rel]))
        return _Stat(rel.split("/")[-1], 2, 0)

    def open(self, path, mode):
        return io.BytesIO(self.tree[path.strip("/")])


def test_read_image_tree_round_trips_nested_files():
    fs = FakeFS({"main.py": b"1", "app/a.py": b"22",
                 "app/tools/b.py": b"333"})
    assert vfi.read_image_tree(fs) == {"main.py": b"1", "app/a.py": b"22",
                                       "app/tools/b.py": b"333"}


def test_staging_files_reads_bytes(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_bytes(b"12345")
    (tmp_path / "b.txt").write_bytes(b"xy")
    assert vfi.staging_files(str(tmp_path)) == {"sub/a.py": b"12345",
                                                "b.txt": b"xy"}


def test_compare_catches_all_difference_kinds():
    want = {"same.py": b"1", "diff.py": b"22", "gone.py": b"3"}
    got = {"same.py": b"1", "diff.py": b"XX", "extra.py": b"4"}
    failures = vfi.compare(want, got)
    assert len(failures) == 3
    assert any("gone.py" in f and "missing" in f for f in failures)
    assert any("diff.py" in f for f in failures)
    assert any("extra.py" in f for f in failures)
    assert vfi.compare(want, dict(want)) == []


def test_main_rejects_broken_image(tmp_path, capsys):
    (tmp_path / "a.py").write_bytes(b"1")
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not a littlefs image" * 64)
    rc = vfi.main(["vfi", str(bad), str(tmp_path)])
    assert rc != 0
