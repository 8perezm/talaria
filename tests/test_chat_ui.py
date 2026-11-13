# test_chat_ui.py — chat reading behaviour that is easy to regress.
#
# Two guarantees, both UX-visible and both previously broken:
#
#   1. The transcript follows streaming output ONLY while the reader is at the
#      tail. Every delta patches the turn and re-renders; an unconditional
#      scroll effect drags the page down while someone is reading further up.
#   2. Model reasoning is a real, expandable block. Providers stream reasoning
#      per-token, so the buffer must accumulate; the expanded/collapsed choice
#      is a reading preference remembered for later blocks and reloads.
#
# Source-audited like tests/test_spa.py and tests/test_theme_fonts.py: the UI
# is a compiled SPA with no JS test runner in this repo, so the contract is
# pinned in the source that produces the shipped bundle.
import os
import re

BASE = os.path.join(os.path.dirname(__file__), "..")
CHAT = os.path.join(BASE, "ui", "src", "pages", "ChatPage.tsx")
BUNDLE = os.path.join(BASE, "www", "assets", "app.js")


def _src():
    with open(CHAT, encoding="utf-8") as f:
        return f.read()


def test_transcript_follows_only_when_the_reader_is_at_the_tail():
    src = _src()
    # A proximity test, not an exact pixel test (sub-pixel scroll heights).
    assert "function isNearBottom" in src
    assert "scrollHeight - el.scrollTop - el.clientHeight" in src
    assert "const BOTTOM_SLOP_PX" in src
    # The scroll handler is what arms/disarms the follow.
    assert "onScroll={handleTranscriptScroll}" in src
    assert "stickToBottomRef.current = stick" in src
    # The delta effect must bail out when the reader scrolled away, then only
    # then move the view.
    idx = src.index("if (!stickToBottomRef.current) return")
    assert "el.scrollTop = el.scrollHeight" in src[idx:idx + 160]
    # Sending is an explicit "take me to the conversation" action.
    assert "stickToBottomRef.current = true" in src
    # And there is an explicit way back into the follow once parked.
    assert "Jump to latest" in src


def test_reasoning_deltas_accumulate_instead_of_replacing():
    src = _src()
    # Reasoning arrives as incremental deltas exactly like content. Replacing
    # the buffer showed only the last fragment.
    assert "reasoning += evt.reasoning" in src
    assert not re.search(r"\breasoning = evt\.reasoning\b", src)


def test_thinking_block_is_expandable_and_remembers_the_choice():
    src = _src()
    assert "THINKING_OPEN_KEY = 'talaria_thinking_open'" in src
    assert "localStorage.setItem(THINKING_OPEN_KEY" in src
    assert "aria-expanded={showThinking}" in src
    # New blocks start from the remembered preference, and toggling one block
    # updates it for the blocks that follow.
    assert "useState(thinkingOpen)" in src
    assert "onThinkingOpen(next)" in src
    # The reasoning body follows its own tail unless the reader scrolls it.
    assert "thinkingStickRef" in src


def test_shipped_bundle_contains_the_chat_fixes():
    # www/ is the artifact the device serves; a source edit without a rebuild
    # would leave the browser running the old behaviour.
    with open(BUNDLE, encoding="utf-8") as f:
        js = f.read()
    assert "Jump to latest" in js
    assert "talaria_thinking_open" in js
