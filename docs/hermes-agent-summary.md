# Hermes-Agent — Thorough Analysis Summary

> Source: https://github.com/nousresearch/hermes-agent
> Local clone: `C:\Users\miguel\AppData\Local\Temp\opencode\hermes-agent` (cloning at time of writing — this doc seeded from official docs + README, to be enriched by direct source read)
> Doc owner: ESP32-agent team — for inspiration / parity ideas for `esuyo-esp32-agent-python`
> Date: 2026-11-07

## 0. TL;DR in 30 seconds

**Hermes Agent** by **Nous Research** is a **self-improving, provider-agnostic, open-source (MIT) AI agent framework** in Python.

- Runs in **terminal (CLI + full TUI), native Electron desktop app, web dashboard, IDEs (via ACP), and 25+ messaging platforms (Telegram, Discord, Slack, WhatsApp, Signal, …)** — all from **one gateway process, one memory, one session store**.
- Core loop is a single **`AIAgent`** class (`run_agent.py` facade → `agent/conversation_loop.py` + `agent/turn_*.py`) that builds a layered system prompt, calls any LLM via 3 API modes, executes **70+ tools in ~28 toolsets** via a central registry, persists to **SQLite + FTS5**, compresses context, and supports fallback providers.
- Differentiator vs Claude Code / Codex / OpenClaw: **closed learning loop** — bounded curated memory (`MEMORY.md` / `USER.md`), **autonomous skill creation + self-improvement** (`skill_manage`, curator, background review), **FTS5 session search**, **Honcho dialectic user modeling**, cron scheduling, subagent delegation, and **trajectory generation for training next-gen tool-calling models**.
- Runs anywhere: `$5 VPS`, GPU cluster, Docker/SSH/Modal/Daytona/Vercel Sandbox terminal backends, serverless hibernation. **Nous Portal** subscription optionally covers models + web-search/image/TTS/browser Tool Gateway under one key, but BYO keys always work.
- Stats (Nov 2026, v0.23.0 "Hearth"): ~261k stars, ~58k forks, ~63k commits, ~1,050-entry plugin catalog, ~25k pytest tests in ~1,250 files.

---

## 1. What it is / what problem it solves

| Aspect | Detail |
|---|---|
| **Product** | Personal AI agent that "grows with you" — remembers projects, learns procedures, automates recurring work, reachable from anywhere. |
| **Surfaces** | CLI (`hermes`), Ink TUI, Electron Desktop, Web dashboard, ACP server (VS Code / Zed / JetBrains), OpenAI-compatible API server, Python library (`from run_agent import AIAgent`), messaging gateway. |
| **Models** | Any provider: Nous Portal (300+ models), OpenRouter, OpenAI (+ Codex Responses API), Anthropic native, Google, DeepSeek, xAI, local endpoints, custom OpenAI-compatible. Switch live with `hermes model` / `/model`. No lock-in. Credential pools, routing, fallback chains, 1h prompt-cache on Claude. |
| **Licence / cost** | MIT. Self-host free. Pay only your model provider / optional Portal sub / optional cloud hosting. |
| **Origin** | Nous Research (of Hermes / DeepHermes LLM fame). Fork-lineage related to OpenClaw migration tooling (`hermes import-agent openclaw|claude-code|codex|cursor`). |

### Positioning vs alternatives

- Same category as **Claude Code, OpenAI Codex CLI, OpenClaw**: autonomous coding/task agents with tool calling.
- Unlike single-terminal agents: **one agent core drives every surface** (design principle: *platform-agnostic core*), sessions have lineage + per-platform isolation but unified routing (single gateway owns each session — v0.23 "hearth" model).
- Unlike stateless bots: **persistent memory + skills + session search** = cross-session recall without stuffing everything into context.
- Research angle: **batch trajectory generation + compression** outputs ShareGPT-format data for training future tool-calling models — Nous dogfoods Hermes to train Hermes models.

---

## 2. How to run it (30s mental install)

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash   # Linux/macOS/WSL2
iex (irm https://hermes-agent.nousresearch.com/install.ps1)          # Windows native (%LOCALAPPDATA%\hermes)
source ~/.bashrc && hermes              # interactive CLI
hermes model                            # pick provider/model
hermes setup --portal                   # optional: OAuth to Nous Portal, enables model + Tool Gateway
hermes gateway setup + hermes gateway start  # Telegram/Discord/… bot
hermes chat -q "fix bug in main.py"     # one-shot
hermes -p work                          # isolated profile (own HERMES_HOME/config/memory/sessions)
```

Key CLI: `hermes tools` (enable/disable toolsets per platform), `hermes skills {browse,search,install,…}`, `hermes bundles`, `hermes cron`, `hermes sessions list`, `hermes journey` (learning timeline), `hermes doctor`, `hermes update`.

---

## 3. Architecture — big picture

```
Entry Points: CLI (cli.py) | Gateway (gateway/run.py) | ACP (acp_adapter/) | Batch Runner | API Server | Python lib
                          \               |                              /
                           v              v                             v
                        AIAgent (run_agent.py facade)
                        + Prompt Builder (prompt_builder.py + system_prompt.py)
                        + Provider Resolution (runtime_provider.py — 18+ providers, 3 API modes)
                        + Tool Dispatch (model_tools.py over tools/registry.py — 70+ tools / ~28 toolsets)
                        + Compression & Caching (context_compressor.py, prompt_caching.py)
                                  |                                  |
                                  v                                  v
                    Session Storage (SQLite+FTS5, hermes_state.py)   Tool Backends (Terminal×7, Browser×5, Web×4, MCP dynamic, …)
```

Design principles (from official docs): **prompt stability** (frozen system prompt per session → prefix-cache hits), **observable execution** (every tool call via callbacks), **interruptible** (API + tools cancellable), **platform-agnostic core**, **loose coupling** (registry + `check_fn` gating), **profile isolation**.

Directory map (top-level, v0.23):

```
run_agent.py, cli.py, model_tools.py, toolsets.py, hermes_state*.py, hermes_constants.py, batch_runner.py
agent/          # conversation_loop.py, turn_*.py, prompt_builder.py, context_compressor.py, auxiliary_client.py, …
hermes_cli/     # main.py, config.py, commands.py, auth*.py, runtime_provider.py, plugins.py, skills*.py, …
tools/          # registry.py + one file per tool + environments/{local,docker,ssh,modal,daytona,vercel_sandbox}
gateway/        # run*.py, session.py, delivery.py, pairing.py, hooks.py, mirror.py + platforms/
plugins/platforms/<name>/  # bundled adapters: telegram, discord, slack, whatsapp, matrix, email, sms, irc, line, teams, …
acp_adapter/ cron/ skills/ optional-skills/ plugin-catalog/ plugins/memory/ plugins/context_engine/
web/ ui-tui/ apps/ tui_gateway/ hermes_platform/ evals/ tests/ (~25k tests)
```

Data flows:

- **CLI turn**: `HermesCLI.process_input → AIAgent.run_conversation → build_system_prompt → resolve_runtime_provider → API call → tool_calls? handle_function_call → loop → display → save SessionDB`.
- **Gateway msg**: `Adapter.on_message → MessageEvent → GatewayRunner._handle_message → auth → session-key → AIAgent → deliver via adapter`.
- **Cron tick**: `load due jobs.json → fresh AIAgent (no history) + attached skills → run → deliver → update next_run`.

---

## 4. Agent loop internals (the heart)

`AIAgent.chat(msg)` → `run_conversation(...)` loop in `agent/conversation_loop.py`:

1. task_id, append user msg, build/reuse cached system prompt.
2. Preflight compression check (>50% window; gateway auto at 85%).
3. Build API messages (OpenAI format internally; convert for `codex_responses` / `anthropic_messages` via `anthropic_adapter.py`).
4. Inject ephemeral layers (budget/context-pressure warnings), Anthropic cache breakpoints.
5. `_interruptible_api_call` — HTTP in bg thread + interrupt event (new user msg / `/stop` / signal abandons thread, no partial inject).
6. If `tool_calls`: dispatch (single → inline; multi → `ThreadPoolExecutor`, order-preserved; `clarify` forces serial), pre/post plugin hooks, `approval.py` gate for dangerous cmds, append `role:tool` results, loop. Four agent-level tools intercepted before registry: `todo`, `memory`, `session_search`, `delegate_task`.
7. Else: persist session, flush memory, return `final_response`.

Other mechanics:

- **3 API modes**: `chat_completions` (OpenAI-compat), `codex_responses` (Responses API), `anthropic_messages` (native). Resolution: explicit arg → provider default → base-URL heuristic → default.
- **Strict alternation**: `User→Assistant→…`, `Assistant(tool_calls)→Tool×n→Assistant`; never two assistants/users in a row; only `tool` may repeat.
- **Callbacks**: `tool_progress, thinking, reasoning, clarify, step, stream_delta, tool_gen, status` — drive CLI spinner / gateway progress / ACP status.
- **Budgets**: default 500 turns (`agent.max_turns`); subagents independent cap 50 (`delegation.max_iterations`). Fallback chain on 429/5xx/401-403 + credential refresh; aux tasks (vision/compress/title) have own chains.
- **Compression**: flush memory → summarize middle turns → keep last N (default 20) + keep tool pairs together → new child lineage ID.
- **Reasoning**: stored in `assistant_msg["reasoning"]`, display-optional.

---

## 5. Prompt system

Tiers `stable → context → volatile`: identity/tool guidance/skills → context files (`.hermes.md, AGENTS.md, CLAUDE.md, SOUL.md, .cursorrules`) → memory/profile/timestamp. Frozen at session start (cache stability); skill adds mid-session arrive as one-shot user-message note, merged at next compaction. Anthropic prefix-cache breakpoints + lossy `context_compressor` summarization + micro-compaction. `@`-references expand files/folders/diffs/URLs inline. Checkpoints snapshot workdir before edits (`/rollback`).

---

## 6. Tools & toolsets (70+ tools, ~28 toolsets)

| Category | Examples |
|---|---|
| Web | `web_search` (4 backends), `web_extract`, `x_search` (xAI-gated, opt-in) |
| Terminal & files | `terminal` (7 backends), `process` (bg mgmt), `read_file` (UTF-16 transcode, 10MB cap), `write_file`/`patch`, `search_files` |
| Browser | `browser_exec` (Python-over-CDP, screenshots), `browser_cdp/dialog/vault`; Camofox via plugin |
| Media | `vision_analyze`, `image_generate` (FAL.ai, 11 models), `text_to_speech` (10 providers + custom), voice-memo transcription |
| Orchestration | `todo`, `clarify`, `execute_code` (sandboxed Python-RPC, zero-context pipelines), `delegate_task` (isolated subagents, default 3 concurrent) |
| Memory | `memory` (add/patch/remove, no read — auto-injected), `session_search` (FTS5, 20ms query) |
| Automation | `cronjob` tool + `cron/` scheduler, `hermes send` delivery |
| Integrations | MCP (stdio/HTTP, per-server filter, sampling), plugin tools (e.g. `ha_*` Home Assistant) |

Toolsets (enable/disable per platform via `hermes tools`): `web, search, terminal, file, browser, vision, image_gen, skills, tts, todo, memory, session_search, cronjob, code_execution, delegation, clarify, messaging, discord(_admin), debugging, safe`, platform presets (`hermes-cli`, `hermes-telegram`, …), dynamic `mcp-<server>`.

Terminal backends: `local | docker (persistent container, shared /workspace) | ssh (recommended isolation) | modal | daytona (hibernate/wake, near-zero idle cost) | vercel_sandbox (snapshots) | singularity/sprites (plugins)`. Hardened: ro-root, no caps, no privesc, PID cap 256, ns isolation. Notable details: non-interactive shell rc guard (`.bashrc` early-return), sudo masked-prompt + `SUDO_PASSWORD`, bg `process` tool with `notify_on_complete` (quiet double-wait → completion delivered as new message), retained receipts (64 newest, 7d, 200k tail, secret-redacted).

Docs: `web_tools.py`, `terminal_tool.py`, `process_registry.py`, `browser_{exec,session,launcher}.py`, `code_execution_tool.py`, `delegate_tool.py`, `mcp_tool*.py`, `approval.py`, `registry.py` (import-time self-registration — no manual list).

---

## 7. The learning loop (why "grows with you")

1. **Bounded curated memory** — `MEMORY.md` (2,200 chars / ~800 tok, env facts/conventions/lessons/diary) + `USER.md` (1,375 chars / ~500 tok, prefs/style). Frozen snapshot in prompt with `§`-separated entries + usage %. Agent manages via `memory` tool (add/patch/remove, substring match, dup-reject, injection-scan, overflow → single batch that frees space + adds). `write_approval` gate → staged `/memory pending|approve|reject`. No auto-compact — model consolidates.
2. **Skills = procedural memory** — `~/.hermes/skills/` single source (+ `external_dirs`, `create_dir`, project-local `.hermes/skills` + `.agents/skills` with trust + scan quarantine). `SKILL.md` frontmatter (`name, description≤60ch, version, platforms, metadata.hermes.{tags,category,fallback_for_*,requires_*,config}`) + When-to-Use/Procedure/Pitfalls/Verification. Progressive disclosure L0 index (~3k tok) → L1 full → L2 refs. Every skill = `/<name>` slash cmd (stackable ×5), bundles (`~/.hermes/skill-bundles/*.yaml`) group them. Agent self-authors via `skill_manage` (create/patch/delete/write_file/… + linter), Hub install scanned (built-in + advisory NVIDIA SkillEvaluator T1), `skills.write_approval` staging, curator consolidation + locks. Compat `agentskills.io`. `/learn <anything>` authors a skill from SDK/docs/URL/conversation/notes/book (books → lean SKILL.md + per-chapter `references/`).
3. **Background self-improvement review** — after each turn, fork replays conversation (same-model: full warm-cache replay; different-model: compact digest) on main or cheaper `auxiliary.background_review.{provider,model}` with token cap, defer-on-local-GPU, extra-tools allowlist; saves memories/skills quietly (`display.memory_notifications: off|on|verbose`). Manual `/refine`, `/journey` timeline (Star Map) with edit/delete/archive.
4. **Session search** — every CLI+gateway session in `~/.hermes/state.db` SQLite FTS5; `session_search` discovery/scroll/browse returns raw messages (no LLM summary, no truncation). Memory (~1.3k tok always-on, instant) vs search (unlimited, ~20ms, on-demand).
5. **Honcho + providers** — dialectic user modeling via `honcho` plugin; also RetainDB/ByteRover built-in + Hindsight/Supermemory/Mem0/OpenViking/Holographic catalog plugins. Single-select, run alongside (or instead of) built-in stores. Nudges (`memory.nudge_interval`, `skills.creation_nudge_interval`) prompt the model to persist.

Practice note from docs: memory needs session boundaries — `/new` at task/topic/day breaks on gateways (CLI invocations are naturally new sessions); otherwise one ever-growing session never lets forget→recall→search fire and just recompacts expensively.

---

## 8. Gateway (messaging + scheduling plane)

Long-lived `GatewayRunner` (`gateway/run.py` + `run_*.py` + `slash_commands_*.py`): 25+ adapters (core `gateway/platforms/` + bundled `plugins/platforms/` — telegram, discord, slack, whatsapp(+cloud), signal, matrix, mattermost, email, sms, dingtalk, feishu, wecom, irc, line, teams, google_chat, ntfy, …; Home Assistant/Yuanbao via catalog). Flow: `Adapter.on_message → MessageEvent → _handle_message → auth (allowlist + DM pairing) → session-key `agent:{ns}:{platform}:{chat_type}:{chat_id}` (never hand-build — `build_session_key`) → slash? → busy? (two-level guard: base-adapter queue+interrupt, runner intercept `/stop|/status|/approve…`) → AIAgent → delivery.py`. Features: thread-aware keys, cross-session mirroring, channel directory (human names for cron delivery), hooks (logging/alerts/webhooks), token locks per profile, multiplexed profiles (`gateway.multiplex_profiles`, per-profile authority + FIFO + exactly-once), local control socket (`identify/resolve-profile/session-ticket`, 0600/POSIX-cred/SID-checked, single-use 30s tickets), canonical WS (`groups.*, session.*, prompt.*, clarify.*, config busy, setup.*, subagent.*`), `hermes gateway {setup,run,start,stop,install,ensure,attach}` with service-install consent (`gateway.service_install_choice`), idle-exit unmanaged mode, crash recovery (never-started queued work only; started→`unknown` + FIFO pause + `/reset|/discard`).

Cron (`cron/jobs.py+scheduler.py`): first-class agent tasks (not shell), JSON store, natural-language or cron-expr schedules, attached skills/scripts, delivery to any platform, pause/resume/edit, multiplex-aware.

Voice/media: mic TUI + Discord voice channels, "Hey Hermes" wake-word, image paste + vision, `[[audio_as_voice]]` / `[[as_document]]` delivery directives, bare-absolute-path media auto-attach.

---

## 9. Providers, config, plugins, other subsystems

- **Provider resolution** (`hermes_cli/runtime_provider.py`): `(provider,model) → (api_mode, key, base_url)`, 18+ providers, OAuth, aliases, credential pools (rotate on 429), routing (sort/allow/deny/priority), per-task aux fallbacks, models.dev registry, frozen-launch-credential recovery.
- **Config**: `~/.hermes/config.yaml` (+ `.env` secrets, never memory) with `DEFAULT_CONFIG`, migration, per-platform overrides, `agent.disabled_toolsets`, `terminal.*`, `memory.*`, `skills.*`, `display.*`, `auxiliary.*`, `hooks.output_spill`, profiles (`hermes -p`, `profile {create,list}`).
- **Plugins**: `~/.hermes/plugins` + `.hermes/plugins` + pip entry-points; tools/hooks/commands via context API; single-select `memory` + `context_engine` types; catalog ~1,050 entries (`hermes plugins install <name>`), self-updating; skills vs plugins distinction (knowledge vs code).
- **Surfaces**: Ink TUI (multiline, autocomplete, history, interrupt-and-redirect, streaming, inline images, `/rewind`), Desktop (Electron, multi-machine, subagent model picker, Star Map, skill installer `hermes://skill/install`), Web dashboard, ACP (stdio/JSON-RPC, chat/diffs/terminal in editor), API server (OpenAI-compat → Open WebUI/LobeChat/…), batch (`batch_runner.py`, parallel ShareGPT trajectories + compression for training).
- **Security**: approval gates (dangerous-cmd heuristics, sudo/secret prompts), skill scan quarantine (prompt-inject/exfil/hidden-Unicode), memory injection scan, container hardening, secret redaction, DM pairing, no secrets in chat on messaging surfaces.
- **Quality**: ~25k pytest tests (~1,250 files), evals/, ownership map, contributing guide, PM venv workflow (`source ./activate`), `hermes doctor`.

---

## 10. Relevance to `esuyo-esp32-agent-python` (ideas worth stealing)

- **Borrow the learning-loop shape at ESP32 scale**: keep our `memory.txt + chatlog.jsonl` but adopt Hermes' split — small always-on facts (our `memory.txt` ≈ their `MEMORY.md+USER.md`) vs on-demand procedures (their skills) vs searchable history (our `chatlog.jsonl` tail — could add keyword search endpoint later).
- **Frozen snapshot + `/new` discipline**: we already inject last-8-turns; document that streamed turns must log (we fixed this) and that gateway-style long sessions need explicit reset — same lesson.
- **Progressive disclosure for tools**: our system prompt lists only enabled tools — same as Hermes toolsets; consider per-page/per-token tool presets.
- **Approval + scans**: Hermes `approval.py` + skill quarantine are the grown-up version of our `/update` blocklist — worth mirroring if we ever allow agent-written files.
- **Subagents + `execute_code` RPC**: not fittable on S3, but the *pattern* (collapse multi-step pipelines into one turn) maps to our need to minimize LLM round-trips over TLS on tiny heap.
- **Trajectory logging**: our `chatlog.jsonl` is already trajectory-adjacent; Hermes ShareGPT format is a good export target for future fine-tunes.

---

## 11. Sources & verification status

- [x] README + badges (install, setup, portal, migration, contributing, license MIT).
- [x] Official docs: Architecture, Agent Loop, Tools, Memory, Skills, Gateway Internals (+ Prompt Assembly, Compression/Caching, Provider Runtime, Session Storage linked for follow-up).
- [x] Web search (stars/forks/release v0.23.0 Hearth notes, Portal/Tool Gateway, Desktop).
- [x] **Source-verified against shallow clone** (`--depth 1`, HEAD `a9ff9799`,
  22,780 files): `run_agent.py` (1,375 lines — mixin-assembled
  `ClientLifecycle/StreamDelivery/SessionPersistence/Compression/TurnFacade…`
  mixins, so the docs' "thin facade" line is outdated), `agent/` (~270 files:
  `conversation_loop.py` 102KB, `prompt_builder.py` 105KB,
  `context_compressor.py` 330KB, `background_review.py` 82KB,
  `memory_manager.py` 53KB), `tools/registry.py` self-registration confirmed
  (53 `registry.register(` calls; cycle-safe `registry → tools →
  model_tools → agent` docstring), `hermes_state*.py` = **65 files** (not ~30),
  memory caps at `hermes_cli/config_defaults.py:1304-1305`
  (`memory_char_limit: 2200`, `user_char_limit: 1375`), load at
  `agent/agent_init.py:1156-1198`, tool actions `add/patch/remove` at
  `tools/memory_tool.py:108-167` (+ schema enum `:418`, `FROZEN snapshot`
  `:3`), `MemoryStore` at `tools/memory_tool_store.py` (limits default
  `:188`, substring match, over-limit error, `_scan_memory_content` `:29`).

> Clone target: `C:\Users\miguel\AppData\Local\Temp\opencode\hermes-agent`
> — shallow `git clone --depth 1 --single-branch
> https://github.com/nousresearch/hermes-agent` (full-history clone killed:
> 710k objects / ~700MB+ at ~1.5MB/s; re-run `git pull --ff-only` if stale —
> note: shallow clone may need `git fetch --unshallow` first for pull).
