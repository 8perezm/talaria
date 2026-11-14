# prompt.py — tiered system prompt assembly (Mini Hermes Phase 1).
# MicroPython-safe: utf-8 only, single-string output, tiny bounded allocations.
# Lazy imports (inside the builder) so host tests and device boot stay light.
try:
    import ujson as json  # noqa: F401 (kept for symmetry with llm.py)
except ImportError:
    import json  # noqa: F401

_CONTEXT_PATHS = (".context.md", "/.context.md")
_CONTEXT_MAX = 1024
_MEM_CAP = 1200


def _read_context():
    """Read the optional project-context file (<=1024 chars). Missing = ''."""
    for path in _CONTEXT_PATHS:
        try:
            with open(path, "r") as f:
                try:
                    text = f.read(_CONTEXT_MAX + 1)
                except TypeError:
                    # very old MicroPython read() takes no size arg
                    text = f.read()
        except OSError:
            continue
        except Exception:
            return ""
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return ""
        if len(text) > _CONTEXT_MAX:
            text = text[:_CONTEXT_MAX]
        return text
    return ""


def _p2(n):
    try:
        n = int(n)
    except Exception:
        return "00"
    if n < 0:
        n = 0
    if n < 10:
        return "0" + str(n)
    return str(n)


def _now_str():
    try:
        import time as _t
        lt = _t.localtime()
        return "%s-%s-%s %s:%s" % (lt[0], _p2(lt[1]), _p2(lt[2]), _p2(lt[3]), _p2(lt[4]))
    except Exception:
        return ""


def _workspace_listing(max_items=12):
    """'weather_panel.py (15B), probe.py (301B)' — bounded, best-effort.

    Name + size only (no mtimes: one stat per entry is already the expensive
    part on littlefs, and the model needs identity, not timestamps).
    """
    import fsutil as _fs
    entries, err = _fs.list_dir(_fs.DATA_WORKSPACE)
    if err or not entries:
        return ""
    out = []
    for e in entries:
        try:
            name = e.get("name", "")
        except Exception:
            continue
        if not name or name.startswith("."):
            continue
        try:
            size = int(e.get("size", 0) or 0)
        except Exception:
            size = 0
        out.append("%s (%dKB)" % (name, (size + 1023) // 1024)
                   if size >= 1024 else "%s (%dB)" % (name, size))
        if len(out) >= max_items:
            break
    return ", ".join(out)


def buildMiniPrompt():
    """Assemble the system prompt in tiers. Returns a single string.

    [stable]   identity + enabled-tools + full-knowledge clause (wording kept
               verbatim from agent_tools.buildSystemPrompt — it fixed the
               "I have no knowledge" refusal).
    [context]  optional /.context.md (<=1024 chars, missing = skipped) +
               frozen memory snapshot (<=1200 chars, as today).
    [volatile] live dev snapshot [ip up heap rssi] + wall-clock time.

    Frozen-per-turn: callers (llm.callLLMWithTools) call this ONCE per turn
    and reuse the string across iterations — do not re-call mid-turn.
    """
    import agent_tools
    parts = ["[stable] "]
    parts.append("You are Talaria Agent, an assistant running on an ESP32-S3 board at talaria-agent.local. "
                 "Reply in plain text. ")
    try:
        names = [t["name"] for i, t in enumerate(agent_tools.TOOL_REGISTRY)
                 if agent_tools.toolEnabledIdx(i)]
    except Exception:
        names = []
    if names:
        parts.append("Enabled device tools: " + ", ".join(names) + ". ")
    else:
        parts.append("Enabled device tools: (none). ")
    # Keep this clause verbatim (see AGENTS.md): without it the model reads
    # "device agent + web_fetch tool" as "I am a shell with no knowledge".
    parts.append("You have full general knowledge. Answer ordinary questions "
                 "(history, geography, science, code, maths, explanations) "
                 "directly and completely from your own knowledge, without "
                 "calling a tool. Never reply that you lack knowledge or that "
                 "you can only look things up on the web. ")
    parts.append("Use a tool ONLY when the request needs live device state "
                 "(pins, GPIO, ADC, wifi, memory, restart), saved procedures, "
                 "scheduled work, or fresh internet "
                 "data. Never guess pin levels or current events. ")
    parts.append("Workspace files live under opt/data/workspace/ (shown as "
                 "/workspace/ in Files); bare names and workspace/... map "
                 "there. read_file, search_files (default root opt/data), "
                 "write_file and patch_file work on them, and a .bak "
                 "checkpoint is kept before each write. Long files are built "
                 "in chunks: write_file append=true adds a <=4KB chunk "
                 "(assembled file <=16KB), then patch_file fixes a span. "
                 "Scripts run in-process via run_script (<=16KB); they may "
                 "import device modules such as screen, epd and framebuf, "
                 "and print up to 1KB. Always write new files under "
                 "opt/data/workspace/. ")
    # The workspace listing is what stops the agent rebuilding work it already
    # did: without it a new turn has no idea weather_panel.py exists, so it
    # re-reads the skill, re-fetches the data and writes a placeholder again.
    # Bounded on purpose (name + size, 12 entries) so the prompt stays small.
    try:
        ws = _workspace_listing()
    except Exception:
        ws = ""
    if ws:
        parts.append("Your workspace already contains: " + ws +
                     ". Read an existing file before rewriting it. ")
    parts.append("When the user asks to save a procedure as a reusable skill, "
                 "draft the full skill text and call skills with action "
                 "create (or propose for a /learn draft, patch/delete to revise): "
                 "writes are quarantine-scanned and, with write-approval on, "
                 "STAGED for human approval in Skills — tell the user to approve "
                 "there. When the user wants something done on a schedule, use "
                 "the cron tool (add/list/edit/pause/resume/remove/run_now, max 5 "
                 "jobs, every 60s..86400s) and confirm the schedule back. "
                 "Cron jobs can also run a workspace script: pass script "
                 "(e.g. workspace/hello.py) with no_agent=true to run the script "
                 "instead of an agent turn, delivering stdout verbatim. ")
    parts.append("Keep chat and acknowledgements short, but give a real, "
                 "complete answer when the user asks a substantive question. "
                 "Always finish with a plain-text reply summarizing tool "
                 "results (never leave the reply empty after tools).")
    parts.append("\n[context]")
    try:
        ctx = _read_context()
    except Exception:
        ctx = ""
    if ctx:
        parts.append(" Project context:\n" + ctx)
    try:
        import memory as _mm
        mem = _mm.snapshot_for_prompt(_MEM_CAP)
    except Exception:
        mem = ""
    if not mem:
        # fallback: legacy single-store text (memory.py missing?)
        try:
            mem = agent_tools.readMemoryFacts()
        except Exception:
            mem = ""
        if mem:
            mem = mem[:_MEM_CAP]
    if mem:
        parts.append("\nLong-term memory:\n" + mem)
    try:
        import skillstore as _sk
        sec = _sk.prompt_section(1024)
    except Exception:
        sec = ""
    if sec:
        parts.append("\n" + sec)
    parts.append("\n[volatile]")
    try:
        ip, up, heap, rssi = agent_tools._live_snapshot()
    except Exception:
        ip, up, heap, rssi = "ap", 0, 0, 0
    parts.append(" [dev ip=%s up=%ds heap=%d rssi=%s]" % (ip, up, heap, rssi))
    now = _now_str()
    if now:
        parts.append(" time=" + now)
    return "".join(parts)
