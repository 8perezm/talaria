import { useState } from 'react'
import { BookOpen, ChevronRight, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Chip, Panel } from '@/components/ui'
import { Markdown } from '@/components/Markdown'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface Section {
  id: string
  title: string
  body: string
}

const SECTIONS: Section[] = [
  {
    id: 'start',
    title: 'Getting started',
    body: `This dashboard is the web face of a **micro Hermes agent** — the same
shell, palette and interaction model as the desktop Hermes Agent, running on
an ESP32-S3 with 8 MB of PSRAM.

## What it can do

- **Chat** with an OpenAI-compatible model, streamed token by token.
- **Call tools on the silicon**: GPIO, ADC, WiFi scan, blink, restart.
- **Read and write files** on the device filesystem.
- **Remember** facts across reboots and **reuse skills** it has been taught.
- **Schedule** unattended cron jobs and deliver to a webhook.
- **Reach the world** over Telegram with an allowlist.

## First run

1. Open **Config** and set the endpoint, model and API key.
2. Open **Chat** and send a message.
3. Open **System → Health** and confirm DNS, upstream and PSRAM are green.

> The device has no internet of its own beyond the upstream API. All pages,
> scripts and styles for this dashboard are compiled into the firmware image
> and served locally, so the UI works on an isolated LAN.`,
  },
  {
    id: 'tools',
    title: 'Tools & toolsets',
    body: `Tools are Python functions the model can call mid-turn. They are grouped
into toolsets such as \`device\`, \`sys\`, \`net\`, \`files\`, \`memory\`, \`skills\`,
\`cron\` and \`delegate\`.

## Enabling and disabling

**Tools** shows every registered tool with its description. Toggling a tool
rewrites the enabled mask in \`config.yaml\`. Disabled tools are not described
to the model at all — it cannot call what it cannot see.

## The agentic loop

A turn works like this:

1. The browser streams via \`/api/chat-stream\`.
2. If the model asks for a tool, the stream emits \`{"need_tools":true}\` and
   stops.
3. The browser falls back to \`/api/chat\`, which runs the full tool loop
   (up to a bounded number of iterations) and returns the final reply.

That two-stage design keeps normal chat fast and streaming, while tool turns
stay correct.`,
  },
  {
    id: 'memory',
    title: 'Memory',
    body: `Two layers, both surviving reboots:

| Store | File | Contents |
| --- | --- | --- |
| Facts | \`memory.txt\` | durable one-liners the agent chose to keep |
| Transcript | \`chatlog.jsonl\` | the rolling conversation log |

The agent writes facts with the \`mem_save\` tool. On a fresh page the Chat view
rehydrates from the transcript tail, so a refresh does not lose the thread.

**Clear** on the Chat page rotates the transcript into \`chatlog.prev.jsonl\`
rather than deleting it — a cheap single-generation backup.`,
  },
  {
    id: 'skills',
    title: 'Skills',
    body: `A skill is a short markdown playbook with a one-line description. The agent
loads a skill only when its description matches the task, so the prompt stays
small.

Skills live in \`skills/<name>.md\` on the device. Write one by hand on the
**Skills** page, or let the agent draft one with \`/learn\`; drafts land in a
pending queue and wait for your approval when write-approval is on.`,
  },
  {
    id: 'cron',
    title: 'Scheduling',
    body: `Cron jobs wake the agent on an interval, run a prompt, and deliver the
result. Intervals are plain seconds (clamped), not cron expressions — a
microcontroller has no wall clock worth trusting across reboots.

Delivery is either \`log\` (the device log, visible on **Logs**) or \`webhook\`
(an HTTPS POST to a URL you supply). Jobs persist in \`cron.json\`.`,
  },
  {
    id: 'channels',
    title: 'Channels',
    body: `Telegram is the outbound channel. The bot token is **file-only**: it lives
in \`tg.json\` on the device and is never accepted over the API.

Pairing works by allowlist. An unknown chat that messages the bot appears under
**Channels → Pairing requests**; approving it adds the chat id to the
allowlist. Only allowlisted chats can drive the agent.`,
  },
  {
    id: 'api',
    title: 'API surface',
    body: `Everything the UI does is a documented JSON call. All \`/api\` routes
require \`Authorization: Bearer <token>\` when an auth token is set.

| Route | Purpose |
| --- | --- |
| \`GET /api/status\` | heap, uptime, WiFi, model, auth state |
| \`GET /api/stats\` | full device counters |
| \`GET /api/doctor\` | DNS/upstream/PSRAM/NTP diagnostics |
| \`GET /api/config\` · \`POST\` | endpoint, model, masked key |
| \`POST /api/chat\` | agentic turn with tools |
| \`POST /api/chat-stream\` | SSE token stream |
| \`GET/POST /api/memory\` | facts, transcript tail, clear |
| \`GET/POST /api/tools\` | tool registry and mask |
| \`GET/POST /api/skills\` | skills CRUD, pending approvals |
| \`GET/POST /api/cron\` | schedule jobs |
| \`GET/POST /api/gateway\` | Telegram pairing |
| \`GET /api/logs\` | ring-buffer console |
| \`GET/POST /api/files*\` | filesystem CRUD |
| \`GET /api/backup\` | redacted settings export |
| \`POST /api/reboot\` | soft reset, wipes nothing |
| \`POST /api/reset\` | **factory wipe** + reboot |`,
  },
]

export function DocsPage() {
  const [active, setActive] = useState(SECTIONS[0].id)
  const section = SECTIONS.find((s) => s.id === active) ?? SECTIONS[0]

  return (
    <>
      <PageHeader title="Documentation" icon={<BookOpen className="h-4 w-4" />} subtitle={<StatusChip />} />
      <PageBody>
        <div className="flex flex-col gap-3 lg:flex-row">
          <nav className="shrink-0 lg:w-56" aria-label="Documentation sections">
            <ul className="flex flex-wrap gap-1 border border-border p-1 lg:flex-col lg:gap-0 lg:border-0 lg:p-0">
              {SECTIONS.map((s) => (
                <li key={s.id} className="lg:w-full">
                  <button
                    type="button"
                    onClick={() => setActive(s.id)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left label-display text-[0.7rem] tracking-[0.1em] transition-colors',
                      active === s.id
                        ? 'bg-midground text-background-base'
                        : 'text-text-secondary hover:bg-midground/8 hover:text-midground lg:border-l lg:border-border',
                    )}
                  >
                    <span className="truncate">{s.title}</span>
                    <ChevronRight className="hidden h-3 w-3 shrink-0 lg:block" />
                  </button>
                </li>
              ))}
            </ul>

            <div className="mt-3 hidden border border-border p-2.5 lg:block">
              <p className="label-display text-[0.6rem] tracking-[0.14em] text-text-faint">Upstream</p>
              <a
                href="https://hermes-agent.nousresearch.com/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 flex items-center gap-1 text-[0.72rem] text-text-secondary hover:text-midground"
              >
                Hermes Agent docs <ExternalLink className="h-3 w-3" />
              </a>
              <a
                href="https://github.com/NousResearch/hermes-agent"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 flex items-center gap-1 text-[0.72rem] text-text-secondary hover:text-midground"
              >
                Source on GitHub <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </nav>

          <Panel
            title={section.title}
            icon={<BookOpen className="h-3.5 w-3.5" />}
            className="min-w-0 flex-1"
            actions={<Chip tone="muted">micro</Chip>}
          >
            <div className="max-w-3xl px-3.5 py-3">
              <Markdown source={section.body} />
            </div>
          </Panel>
        </div>
      </PageBody>
    </>
  )
}
