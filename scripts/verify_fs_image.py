"""Verify a mklittlefs image against the staging dir by mounting it.

Do NOT verify via `mklittlefs -l`: its listing display mangles nested paths
(`//appserver.py` for `/app/server.py`, even on Linux) while the image
itself is correct. Instead this mounts the image with littlefs-python — the
same littlefs format family MicroPython reads — and compares every file by
name AND bytes. Fails loudly on any missing / extra / differing file.

Usage: python3 scripts/verify_fs_image.py <image> <staging>
Host-side CPython only (runs in CI). Pure helpers (read_image_tree,
staging_files, compare) are pinned by tests/test_verify_fs_image.py using a
fake fs object, so the tests need no littlefs install.
"""

import io
import os
import shutil
import sys
import tempfile

# littlefs entry types (lfs.h: LFS_TYPE_REG = 1, LFS_TYPE_DIR = 2).
_REG = 1
_DIR = 2


def read_image_tree(fs):
    """Walk a mounted littlefs (scandir/stat/open interface) -> {path: bytes}.

    Paths are posix, relative, without leading slash.
    """
    out = {}

    def walk(dirpath):
        for entry in fs.scandir(dirpath if dirpath else "/"):
            name = entry.name
            full = (dirpath + "/" + name).lstrip("/") if dirpath else name
            if entry.type == _DIR:
                walk(full)
            elif entry.type == _REG:
                with fs.open("/" + full, "rb") as f:
                    out[full] = f.read()
            # anything else (superblock artefacts) is ignored

    walk("")
    return out


def staging_files(root):
    """Return {posix_rel_path: bytes} for every file under root."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as f:
                out[rel] = f.read()
    return out


def compare(want, got):
    """Return a list of human-readable differences (empty = identical)."""
    failures = []
    for name in sorted(want):
        if name not in got:
            failures.append("missing from image: %s" % name)
        elif got[name] != want[name]:
            failures.append("content differs in image: %s "
                            "(image %d B, staging %d B)"
                            % (name, len(got[name]), len(want[name])))
    for name in sorted(got):
        if name not in want:
            failures.append("unexpected extra in image: %s" % name)
    return failures


def mount_image(image_path, block_size=4096):
    """Mount a littlefs image file read-mostly via littlefs-python.

    Mounts a private copy so verification can never alter the release file.
    Returns (fs_object, cleanup_callable).
    """
    from littlefs import LittleFS, UserContextFile
    size = os.stat(image_path)[6]
    if size % block_size != 0:
        raise ValueError("image size %d not a multiple of block size %d"
                         % (size, block_size))
    tmp = tempfile.mkdtemp(prefix="fsverify")
    copy = os.path.join(tmp, "image.bin")
    shutil.copyfile(image_path, copy)
    fs = LittleFS(context=UserContextFile(copy),
                  block_size=block_size,
                  block_count=size // block_size,
                  mount=True)
    return fs, lambda: shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    if len(argv) != 3:
        print("usage: verify_fs_image.py <image> <staging>")
        return 2
    _self, image, staging = argv
    try:
        fs, cleanup = mount_image(image)
    except ImportError:
        print("FAIL: littlefs-python is not installed "
              "(pip install littlefs-python)")
        return 1
    except Exception as e:
        print("FAIL: cannot mount image: %s" % e)
        return 1
    try:
        got = read_image_tree(fs)
    finally:
        cleanup()
    want = staging_files(staging)
    print("staged=%d imaged=%d" % (len(want), len(got)))
    failures = compare(want, got)
    if failures:
        print("FAIL:")
        for line in failures:
            print("  " + line)
        return 1
    print("OK: every staged file present with identical bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
