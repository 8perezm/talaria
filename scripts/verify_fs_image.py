"""Verify a mklittlefs image against the staging dir: same files, same sizes.

Usage: python3 scripts/verify_fs_image.py <mklittlefs> <image> <staging>

Parses `mklittlefs -l` tolerantly (size-first or name-first lines, headers
and directory entries skipped). Fails loudly — printing the raw listing —
on any missing file, size mismatch, unexpected extra, or unparseable output.
Host-side CPython only (runs in CI, covered by tests/test_esp_deploy.py
conventions for pure helpers where practical).
"""

import os
import subprocess
import sys


def parse_listing(text):
    """Return {posix_path: size} from `mklittlefs -l` output.

    Real line shapes (tabs shown as spaces):
      100 TAB /app/server.py TAB Mon Nov 09 01:31:40 2026
      <dir> TAB /app TAB Mon Nov 09 01:31:40 2026
    i.e. size-first file rows with a trailing date, and <dir> rows that must
    be skipped outright (the trailing year would otherwise parse as a file
    with a bogus size, and the dir itself is not in the staging file set).
    """
    got = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("<dir>"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            size, name = int(parts[0]), parts[1]
        elif len(parts) == 2 and parts[1].isdigit():
            name, size = parts[0], int(parts[1])
        else:
            continue  # header or unparseable line — skip
        name = name.strip().lstrip("./").lstrip("/")
        if name:
            got[name] = size
    return got


def staging_files(root):
    """Return {posix_rel_path: size} for every file under root."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out[rel] = os.stat(full)[6]
    return out


def main(argv):
    if len(argv) != 4:
        print("usage: verify_fs_image.py <mklittlefs> <image> <staging>")
        return 2
    _self, mkl, image, staging = argv
    proc = subprocess.run([mkl, "-l", image],
                          capture_output=True, text=True)
    listing = (proc.stdout or "") + (proc.stderr or "")
    print("--- mklittlefs -l ---")
    print(listing.strip() or "<empty>")
    if proc.returncode != 0:
        print("FAIL: mklittlefs -l exited %d" % proc.returncode)
        return 1
    got = parse_listing(listing)
    want = staging_files(staging)
    if not got:
        print("FAIL: parsed zero files from the image listing")
        return 1
    failures = []
    for name in sorted(want):
        if name not in got:
            failures.append("missing from image: %s" % name)
        elif got[name] != want[name]:
            failures.append("size mismatch %s: image=%d staging=%d"
                            % (name, got[name], want[name]))
    for name in sorted(got):
        if name not in want:
            failures.append("unexpected extra in image: %s" % name)
    print("staged=%d imaged=%d" % (len(want), len(got)))
    if failures:
        print("FAIL:")
        for line in failures:
            print("  " + line)
        return 1
    print("OK: every staged file present with matching size")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
