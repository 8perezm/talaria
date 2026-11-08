# Parity matrix — Hermes Agent → Mini Hermes (ESP32-S3)

Legend: **Full** = same behavior · **Mini** = same shape, smaller limits ·
**API-only** = no tool slot spent · **Defer** = stubbed/post-v1 · **No** = won't fit.

| Hermes capability | Mini target | Verdict | Notes / limits |
|---|---|---|---|
| `AIAgent.run_conversation` loop | `agent_core.py` over `llm.callLLMWithTools` | Mini | max_iters cfg 3–5 (vs 500); sequential tools only (no ThreadPool) |
| 3 API modes (chat/response/anthropic) | OpenAI-compat primary + fallback | Mini | one fallback; failover on 429/5xx/transport fail |
| Tool registry + dispatch + approval | keep `tools/registry.py`, +13 tools (§4 budget) | Full | 23/32 slots; dangerous tools off-by-default |
| Toolsets per platform | tool groups on `/functions` + gateway hiding | Mini | no dynamic `mcp-*` |
| `MEMORY.md`/`USER.md` bounded | `memory.txt` 2200 + `user.txt` 1375 chars | Full | same caps, `§`→`- ` lines, usage % headers |
| `memory` add/patch/remove + overflow batch | same semantics in `memory.py` | Full | jsonl-free, substring match, dup-reject, injection scan |
| `write_approval` staging | `pending_mem.json` + modal review | Full | same `/pending|approve|reject` verbs |
| Skills + progressive disclosure L0→L2 | single-file `skills/<n>.md`, L0 index ≤1KB | Mini | ≤12 skills × 3KB; no `references/` dirs v1 |
| `skill_manage` + linter + locks | API + staged approval; quarantine scan | Mini | locks via blocklist; linter = size/shape checks |
| `/learn` authoring | agent drafts → staged → approve | Full | same flow, human gate mandatory |
| Bundles | `bundles.json` + `/bundle` | Full | trivial at our scale |
| FTS5 `session_search` | keyword scan over jsonl + rotation | Mini | ms-scale on 32KB; no ranking beyond recency+hits |
| Sessions + lineage + `/new`/`/resume` | single active + `.prev` rotation | Mini | `/new` = rotate+clear; no branching |
| `/journey` Star Map | `GET /api/journey` feed + mini timeline | Mini | same data story, plain HTML |
| Cron agent-tasks + delivery | `cron.py`, ≤5 jobs, 60s tick | Mini | interval schedules v1; cron-expr only if cheap to parse |
| `delegate_task` subagents | 1 level, sequential, allowlisted | Mini | ≤2/turn; no parallel (no threads) |
| `execute_code` RPC | `exec_py` sandbox | Mini | block `machine/network/os`; caps; off by default |
| `todo`/`clarify` | `todo` tool; clarify = plain-text question | Mini | no interactive prompt plumbing |
| Checkpoints `/rollback` | `.bak` rotation + API | Full | same guarantee, 8 backups max |
| `read/write/patch/search` files | tools reusing `_fs_*` + caps | Full | 100KB/200KB caps kept |
| Gateway 25+ platforms | web + Telegram poller | Mini | session keys `mini:{p}:{chat}`, allowlist+pairing, per-session busy guard |
| Cron/multiplex/fifo semantics | per-session FIFO, exactly-once tick | Mini | single profile; no `-p` isolation |
| Voice/wake-word/TTS | No | No | mic + streaming audio don't fit; text voice-memos ignored v1 |
| Vision/image-paste/generate | Defer | Defer | multimodal depends on provider; revisit post-v1 |
| Browser automation | No | No | `web_fetch`/`web_search` extract cover the need |
| Terminal backends (docker/ssh/…) | No | No | device *is* the terminal; `exec_py` is the sandbox |
| MCP + plugin catalog | Defer | Defer | config-gated optional tools are the mini equivalent |
| Profiles (`-p`) | No | No | one home; Telegram chats share stores (documented) |
| Prompt cache directives | No | No | frozen-per-turn prompt is the cache-friendly equivalent |
| Batch trajectories | ShareGPT export endpoint | API-only | same format, on-demand not parallel |
| Desktop/TUI/ACP/API server | web UI only (+ compat export) | Mini | 9 pages + journey; no Electron/ACP |
| `hermes doctor` | `/api/doctor` | Full | incl. firmware-variant + heap verdicts (our #1 failure mode) |
| Skills Hub install | manual file add + `/learn` (+URL fetch) | Mini | no registry client on device |

P1 (must, Phases 0–5): loop hardening, memory v2, skills, search, cron, doctor.
P2 (should, Phases 6–8): delegation, exec_py, file tools, checkpoints, Telegram.
P3 (stretch, Phase 9+): trajectory export, compat API, 2nd platform, vision retry.
