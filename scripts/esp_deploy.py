"""Bulk upload + verify for the ESP32-S3 board (host-side, CPython only).

One CLI invocation uploads N files, so the agent spends one tool call per
batch instead of one per file.  Verification is built in: after copying,
device sizes are read back over the same link and compared to the local
sizes.  An echoed "cp ok" proves nothing — only SIZE equality passes.

Usage (run from the repo root):
    python scripts/esp_deploy.py server.py llm.py
    python scripts/esp_deploy.py www/assets/app.js www/index.html --reset
    python scripts/esp_deploy.py --verify-only server.py llm.py --reset
    python scripts/esp_deploy.py --raw server.py llm.py --reset
    python scripts/esp_deploy.py --port COM11 --reset server.py

Spec format: LOCAL[:REMOTE].  REMOTE defaults to the repo-relative local
path with forward slashes (www\\assets\\app.js -> www/assets/app.js).

Modes:
  default  one `mpremote cp` per file (separate subprocess each — mpremote
           misparses chained `cp a :a cp b :b`, so the loop lives here),
           one batched `mpremote exec` stat for verification.
  --raw    a single raw-serial REPL session uploads every file as base64
           chunks (immune to CRLF mangling, unlike repr() chunks) and stats
           each file on the same connection.  No mpremote subprocesses.
  --verify-only  skip the copy, just compare device sizes to local sizes.

Any REPL contact (mpremote or raw) Ctrl-C's the running app; the server is
down until a reset.  Pass --reset to reboot after the batch, then confirm
`WiFi OK:` over HTTP instead of via REPL.

Exit codes: 0 = all OK, 1 = any failure, 2 = usage error.
"""

import argparse
import base64
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACEBACK_MARK = "Traceback (most recent call last)"
STAT_TAG = "STATSIZE"
CHUNK = 512  # binary bytes per base64 chunk (raw mode)


# --------------------------------------------------------------------------
# Pure helpers (hardware-free, covered by tests/test_esp_deploy.py).
# --------------------------------------------------------------------------

def contains_traceback(out):
    """True only on a real MicroPython traceback block.

    Never match bare "Error": file contents (e.g. JS `new Error(...)`)
    echo back over the REPL and cause false failures.
    """
    return TRACEBACK_MARK in (out or "")


def remote_for_local(local_rel):
    """Repo-relative local path -> device remote path (posix, no leading /)."""
    return local_rel.replace(os.sep, "/").replace("\\", "/").lstrip("/")


def parse_spec(arg, root=ROOT):
    """Split LOCAL[:REMOTE] into (absolute local path, remote posix path).

    The split is on the LAST colon, except a bare Windows drive prefix
    (`C:\\...`): `C:\\repo\\a.py` stays whole, while
    `C:\\repo\\a.py:tools/a.py` still splits into local + remote.
    """
    head, sep, tail = arg.rpartition(":")
    if sep and head and tail and not (
        len(head) == 1 and head.isalpha()
    ) and "\\" not in tail:
        local, remote = head, tail.replace("\\", "/").lstrip("/")
    else:
        local, remote = arg, None
    if not os.path.isabs(local):
        local = os.path.join(root, local)
    local = os.path.normpath(local)
    if remote is None:
        rel = os.path.relpath(local, root)
        remote = remote_for_local(rel)
    return local, remote


def parent_dirs(remotes):
    """Ordered unique parent dirs for `remotes`, shallow first.

    Expands intermediates so `www/assets` yields [`www`, `www/assets`];
    `server.py` (root) yields nothing.
    """
    out = []
    seen = set()
    for remote in remotes:
        parts = remote.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d and d not in seen:
                seen.add(d)
                out.append(d)
    return out


def mkdir_snippet(dirs):
    """Device-side Python that mkdirs every dir, ignoring existing ones."""
    lines = ["import os"]
    lines.append("for _d in %r:" % (list(dirs),))
    lines.append(" try:\n  os.mkdir(_d)\n except OSError:\n  pass")
    return "\n".join(lines)


def stat_snippet(remotes):
    """Device-side Python printing one `STATSIZE <remote> <size|ERR>` line each."""
    lines = ["import os"]
    lines.append("for _p in %r:" % (list(remotes),))
    lines.append(
        " try:\n"
        "  print('%s', _p, os.stat(_p)[6])\n"
        " except OSError:\n"
        "  print('%s', _p, 'ERR')" % (STAT_TAG, STAT_TAG)
    )
    return "\n".join(lines)


def parse_stat_output(out, remotes):
    """Parse batched STATSIZE lines -> {remote: size-or-None}."""
    sizes = {}
    for line in (out or "").replace("\r", "").splitlines():
        line = line.strip()
        if not line.startswith(STAT_TAG):
            continue
        bits = line.split()
        if len(bits) != 3:
            continue
        _, remote, size = bits
        if remote in remotes and remote not in sizes:
            sizes[remote] = int(size) if size.isdigit() else None
    return sizes


# --------------------------------------------------------------------------
# Port detection (needs pyserial; kept out of the pure helpers for tests).
# --------------------------------------------------------------------------

def find_port(explicit=None):
    if explicit and explicit.lower() != "auto":
        return explicit
    try:
        from serial.tools import list_ports
    except Exception:
        return explicit if explicit else "COM11"
    cands = list(list_ports.comports())
    if not cands:
        return explicit if explicit else "COM11"
    # Prefer the CH343 UART bridge (stable), then native-USB 303A, then first.
    def key(p):
        vid, pid = (getattr(p, "vid", None), getattr(p, "pid", None))
        if vid == 0x1A86 and pid == 0x55D3:
            return (0, p.device)
        if vid == 0x303A:
            return (1, p.device)
        return (2, p.device)
    cands.sort(key=key)
    return cands[0].device


# --------------------------------------------------------------------------
# mpremote backend: one subprocess per cp, ONE batched exec for verify.
# --------------------------------------------------------------------------

def _run(cmd, timeout):
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timeout after %ds: %s" % (timeout, " ".join(cmd))
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return None, "exit %d: %s" % (proc.returncode, out.strip()[-300:])
    return out, ""


def mpremote_cp(port, local, remote, timeout=300):
    out, err = _run(
        [sys.executable, "-m", "mpremote", "connect", port,
         "cp", local, ":" + remote],
        timeout)
    if out is None:
        return False, err
    if contains_traceback(out):
        return False, "traceback: " + out.strip()[-300:]
    return True, "copied"


def mpremote_exec(port, code, timeout=120):
    return _run(
        [sys.executable, "-m", "mpremote", "connect", port,
         "exec", code],
        timeout)


def mpremote_ensure_dirs(port, dirs, timeout=120):
    if not dirs:
        return True, "no new dirs"
    out, err = mpremote_exec(port, mkdir_snippet(dirs), timeout)
    if out is None:
        return False, err
    if contains_traceback(out):
        return False, "traceback: " + out.strip()[-300:]
    return True, "dirs ok"


def mpremote_batch_stat(port, remotes, timeout=120):
    out, err = mpremote_exec(port, stat_snippet(remotes), timeout)
    if out is None:
        return {}, err
    if not out.strip():
        return {}, "empty response from device"
    return parse_stat_output(out, remotes), ""


def mpremote_reset(port, timeout=60):
    out, err = _run(
        [sys.executable, "-m", "mpremote", "connect", port, "reset"],
        timeout)
    if out is None:
        return False, err
    return True, "reset sent"


# --------------------------------------------------------------------------
# Raw-serial backend: ONE session for mkdirs + all uploads + all verifies.
# --------------------------------------------------------------------------

class RawSession:
    def __init__(self, port, baud=115200):
        import serial  # lazy: tests never touch this path
        self.s = serial.Serial(port, baud, timeout=0.5)
        time.sleep(0.5)
        self.s.reset_input_buffer()

    def _wait_prompt(self, timeout=25):
        buf = ""
        t0 = time.time()
        while time.time() - t0 < timeout:
            d = self.s.read(4096)
            if d:
                buf += d.decode(errors="replace")
                if buf.rstrip().endswith(">>>"):
                    return buf
            else:
                time.sleep(0.05)
        return buf

    def cmd(self, code, timeout=25):
        self.s.write((code + "\r\n").encode())
        return self._wait_prompt(timeout)

    def stop_app(self, boot_timeout=25):
        # Opening the port can DTR-reset the board. If a boot banner is in
        # flight, wait for the app to finish booting first — Ctrl-C during
        # the WiFi connect lands nowhere and the following commands fail
        # with empty responses.
        buf = ""
        t0 = time.time()
        saw_boot = False
        while time.time() - t0 < 3.0:
            d = self.s.read(2048)
            if d:
                buf += d.decode(errors="replace")
                if "=== Agent boot ===" in buf or "[fs] ok" in buf:
                    saw_boot = True
                    break
        if saw_boot:
            rest = ""
            t1 = time.time()
            while time.time() - t1 < boot_timeout:
                d = self.s.read(2048)
                if d:
                    rest += d.decode(errors="replace")
                    if "endpoint" in rest or "Mode:" in rest:
                        break
            time.sleep(0.5)
            self.s.reset_input_buffer()
        self.s.write(b"\x03")
        time.sleep(1.0)
        self.s.reset_input_buffer()
        out = self.cmd("print('IN-REPL')")
        return "IN-REPL" in out

    def write_file(self, local, remote):
        with open(local, "rb") as f:
            data = f.read()
        out = self.cmd("_f=open(%r,'wb')" % remote)
        if contains_traceback(out) or ">>>" not in out:
            return False, "open failed: " + (out or "<empty>")[-200:]
        for off in range(0, len(data), CHUNK):
            b64 = base64.b64encode(data[off:off + CHUNK]).decode()
            out = self.cmd("_f.write(binascii.a2b_base64('%s'))" % b64)
            if contains_traceback(out):
                self.cmd("_f.close()")
                return False, "write failed at offset %d" % off
            if not out.strip():
                self.cmd("_f.close()")
                return False, "empty response at offset %d" % off
        out = self.cmd("_f.close()")
        if contains_traceback(out):
            return False, "close failed"
        out = self.cmd("import os; print('%s %s', os.stat(%r)[6])"
                       % (STAT_TAG, remote, remote))
        sizes = parse_stat_output(out, [remote])
        if sizes.get(remote) != len(data):
            return False, "size mismatch want=%d got=%s" % (
                len(data), sizes.get(remote))
        return True, "%d bytes" % len(data)

    def reset(self):
        self.s.write(b"\x04")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        description="Upload N files to the ESP32 in one invocation, "
                    "with size verification.")
    ap.add_argument("specs", nargs="*", metavar="LOCAL[:REMOTE]",
                    help="files to upload (remote defaults to repo-relative path)")
    ap.add_argument("--port", default="auto",
                    help="serial port (default: auto-detect CH343, else COM11)")
    ap.add_argument("--root", default=ROOT,
                    help="repo root that relative paths resolve against")
    ap.add_argument("--raw", action="store_true",
                    help="single raw-serial session instead of mpremote")
    ap.add_argument("--verify-only", action="store_true",
                    help="skip the copy, only compare device sizes to local")
    ap.add_argument("--reset", action="store_true",
                    help="reset the board after the batch (server is down until reset)")
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-file copy timeout in seconds (default 300)")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.specs:
        ap.print_usage(sys.stderr)
        return 2

    pairs = []
    for spec in args.specs:
        local, remote = parse_spec(spec, args.root)
        if not os.path.isfile(local):
            print("FAIL %s: missing local file %s" % (spec, local))
            return 2
        pairs.append((local, remote))
    remotes = [r for _, r in pairs]
    want = {r: os.stat(local)[6] for local, r in pairs}
    port = find_port(args.port)
    print("port %s  files %d  mode %s" % (
        port, len(pairs), "raw" if args.raw else "mpremote"))

    failures = []

    if args.raw:
        try:
            sess = RawSession(port)
        except Exception as ex:
            print("FAIL: cannot open %s: %s" % (port, ex))
            return 1
        print("stopping app...", end=" ", flush=True)
        if not sess.stop_app():
            # Opening the port sometimes DTR-resets the board mid-boot; the
            # first Ctrl-C then lands nowhere. One retry after a short wait
            # covers the slow-DHCP boot without paying for it every time.
            time.sleep(5.0)
            if not sess.stop_app():
                print("NO REPL — the board is still booting or the port is wrong.")
                sess.close()
                return 1
        sess.cmd("import binascii")
        print("in-repl")
        ok, msg = True, ""
        dirs = parent_dirs(remotes)
        if dirs:
            out = sess.cmd(mkdir_snippet(dirs))
            ok = not contains_traceback(out)
            msg = "dirs ok" if ok else "mkdir failed"
            print("  mkdirs: %s" % msg)
            if not ok:
                failures.append("<mkdirs>")
        if args.verify_only:
            for local, remote in pairs:
                out = sess.cmd(
                    "import os; print('%s %s', os.stat(%r)[6])"
                    % (STAT_TAG, remote, remote))
                got = parse_stat_output(out, [remote]).get(remote)
                if got == want[remote]:
                    print("  OK   %-32s %d bytes" % (remote, got))
                else:
                    print("  FAIL %-32s device=%s local=%d"
                          % (remote, got, want[remote]))
                    failures.append(remote)
        else:
            for local, remote in pairs:
                good, msg = sess.write_file(local, remote)
                print("  %s %-32s %s"
                      % ("OK  " if good else "FAIL", remote, msg))
                if not good:
                    failures.append(remote)
        if args.reset:
            print("resetting...")
            sess.reset()
            time.sleep(1.0)
        sess.close()
    else:
        if not args.verify_only:
            ok, msg = mpremote_ensure_dirs(port, parent_dirs(remotes))
            print("  mkdirs: %s" % msg)
            if not ok:
                print("FAIL <mkdirs>: %s" % msg)
                return 1
            for local, remote in pairs:
                good, msg = mpremote_cp(port, local, remote, args.timeout)
                print("  %s %-32s %s (%d B)"
                      % ("OK  " if good else "FAIL", remote, msg,
                         want[remote]))
                if not good:
                    failures.append(remote)
        # ONE batched stat for the whole batch (not one exec per file).
        got_map, err = mpremote_batch_stat(port, remotes)
        if err:
            print("FAIL <verify>: %s" % err)
            return 1
        for _, remote in pairs:
            if remote in failures:
                continue
            got, exp = got_map.get(remote), want[remote]
            if got == exp:
                print("  VERIFIED %-26s %d bytes" % (remote, exp))
            else:
                print("  FAIL     %-26s device=%s local=%d"
                      % (remote, got, exp))
                failures.append(remote)
        if args.reset:
            ok, msg = mpremote_reset(port)
            print("  reset: %s" % msg)

    ok_n = len(pairs) - len(set(failures))
    print("SUMMARY ok=%d fail=%d" % (ok_n, len(set(failures))))
    if set(failures):
        print("FAILED: " + ", ".join(sorted(set(failures))))
    if not args.reset:
        print("note: REPL contact stops the app — pass --reset (or press "
              "the RESET button) and confirm WiFi OK: over HTTP.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
