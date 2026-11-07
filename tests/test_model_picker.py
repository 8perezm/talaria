import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(ROOT, "www", name), encoding="utf-8") as f:
        return f.read()


def _inline_scripts(src):
    """Yield bodies of inline <script> blocks (no src=)."""
    out = []
    idx = 0
    while True:
        s = src.find("<script", idx)
        if s < 0:
            break
        gt = src.find(">", s)
        tag = src[s:gt + 1]
        e = src.find("</script>", gt)
        assert e >= 0, "unterminated <script> block"
        if "src=" not in tag and src[gt + 1:e].strip():
            out.append(src[gt + 1:e])
        idx = e + 9
    return out


def test_chat_pick_model_parens_balanced():
    # Regression: a dropped ')' in pickModel was a whole-script parse error
    # that silently killed the composer picker (and everything else in the
    # block). The exact fixed line must be present.
    src = _src("chat.html")
    assert "toast('Save failed: '+(j.error||r.status));" in src
    assert "toast('Save failed: '+(j.error||r.status);" not in \
        src.replace("toast('Save failed: '+(j.error||r.status));", "")


def test_agent_model_picker_mirrors_composer():
    src = _src("agent.html")
    for token in ('id="mpill"', 'id="mpop"', 'id="msearch"', 'id="mgroups"',
                  'id="modelmanual"', "'/api/models'", "agent_starred",
                  "setModel(s.model", "STARRED", "renderPopup",
                  "mstar", "pickModel"):
        assert token in src, "missing picker piece: %s" % token
    # model value now lives in a hidden input (pill shows it); the old
    # free-text-only input is gone.
    assert '<input type="hidden" id="model"/>' in src
    assert '<input id="model" placeholder' not in src
    # picking on /agent only stages the value — saving stays on Save button.
    assert "press Save agent settings" in src


def test_inline_js_parses():
    """Parse-check every inline script with node when available.

    A single syntax slip in these single-line blobs breaks the whole page
    script (this exact failure killed the composer picker). Skipped where
    node is not installed; CI/dev machines with node get the real gate.
    """
    import shutil
    import subprocess
    import tempfile
    if shutil.which("node") is None:
        import pytest
        pytest.skip("node not available")
    import glob
    pages = glob.glob(os.path.join(ROOT, "www", "*.html"))
    assert len(pages) >= 9
    with tempfile.TemporaryDirectory() as tmp:
        for p in pages:
            for i, body in enumerate(_inline_scripts(open(p, encoding="utf-8").read())):
                f = os.path.join(tmp, "b%d.js" % i)
                open(f, "w", encoding="utf-8").write(body)
                r = subprocess.run(["node", "--check", f],
                                   capture_output=True, text=True, timeout=30)
                assert r.returncode == 0, "%s block %d: %s" % (
                    os.path.basename(p), i, r.stderr[:1500])
