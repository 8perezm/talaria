"""One-shot maintenance: drop test functions that pinned the retired
hand-written HTML pages (www/*.html). The React SPA replaced them, and
tests/test_spa.py now covers the same guarantees."""
import io
import os
import re
import sys

BASE = os.path.join(os.path.dirname(__file__), "..", "tests")

DELETE_FILES = [
    "test_dash0.py",
    "test_dash2.py",
    "test_dash4.py",
    "test_dash5.py",
    "test_dash6.py",
    "test_dash7a.py",
    "test_model_picker.py",
]

REMOVE = {
    "test_dash3.py": [
        "test_dash3_keys_size_cap", "test_dash3_nav_parity",
        "test_dash3_zero_native_dialogs", "test_dash3_keys_inline_js_parses",
        "test_dash3_keys_route_registered", "test_dash3_keys_route_serves",
        "test_keys_markers", "test_dash3_links_all_resolve",
        "test_redaction_matrix", "test_dash3_stats_counters_via_api",
        "test_chat_turn_increments_counters", "test_chat_stream_fake_turn_counts",
    ],
    "test_dash7b.py": [
        "test_dash7b_shell_page_set", "test_dash7b_retrofit_parity",
        "test_dash7b_topnav_buttons_kept", "test_dash7b_dark_tokens",
        "test_dash7b_per_page_markers", "test_dash7b_size_caps_and_growth",
        "test_dash7b_links_all_resolve", "test_dash7b_inline_js_parses",
        "test_dash7b_zero_native_dialogs", "test_dash7b_theme_toggle_absent_everywhere",
        "test_dash7b_dark_first_marker_on_recolored", "test_dash7b_lf_only_touched",
    ],
    "test_console.py": [
        "test_all_pages_have_console_button_and_drawer",
        "test_console_fetches_logs_and_status_with_auth",
        "test_console_has_reload_pause_copy_clear_close",
        "test_console_drawer_is_resizable",
        "test_console_drawer_has_no_upward_fade",
        "test_no_native_dialogs_app_wide",
    ],
    "test_stats.py": [
        "test_stats_page_exists", "test_stats_page_wide_grid",
        "test_no_native_dialogs_in_stats", "test_chat_status_line_removed",
        "test_nav_has_stats_everywhere", "test_routes_registered",
    ],
    "test_mini_phase9.py": [
        "test_journey_route_and_page", "test_agent_page_markers",
        "test_functions_page_markers", "test_chat_slash_markers",
        "test_docs_mini_hermes_markers", "test_nav_has_journey_everywhere",
        "test_modal_pattern_present",
    ],
    "test_conversation_memory.py": [
        "test_chat_page_restores_transcript_from_device_memory",
        "test_clear_dialogs_are_in_page_modals",
    ],
}


def strip_function(lines, name):
    pattern = re.compile(r"^(async def|def)\s+%s\s*\(" % re.escape(name))
    start = None
    for i, line in enumerate(lines):
        if pattern.match(line):
            start = i
            break
    if start is None:
        return lines, False
    while start > 0 and lines[start - 1].startswith("@"):
        start -= 1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(async def|def|class)\s+\w", lines[j]) or lines[j].startswith("@app"):
            end = j
            break
    # keep trailing comments/blank lines with the following function
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return lines[:start] + lines[end:], True


def main():
    for name in DELETE_FILES:
        path = os.path.join(BASE, name)
        if os.path.exists(path):
            os.remove(path)
            print("deleted", name)

    for name, funcs in REMOVE.items():
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            print("missing", name)
            continue
        src = io.open(path, encoding="utf-8").read()
        lines = src.splitlines(keepends=True)
        removed = 0
        for func in funcs:
            lines, ok = strip_function(lines, func)
            removed += 1 if ok else 0
        io.open(path, "w", encoding="utf-8", newline="").write("".join(lines))
        print("trimmed %s (%d functions)" % (name, removed))


if __name__ == "__main__":
    sys.exit(main())
