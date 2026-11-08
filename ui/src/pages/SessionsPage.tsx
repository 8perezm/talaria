import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { ChevronRight, MessageSquare, Search, Trash2, Download } from 'lucide-react'
import { api, type MemoryResponse } from '@/lib/api'
import { bytes, cn, relativeTime } from '@/lib/utils'
import { usePolled } from '@/lib/app-data'
import { Button, Chip, EmptyState, ErrorNote, Loading, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface TrajectoryConversation {
  from?: string
  value?: string
  ts?: number
}

interface TrajectoryResponse {
  success?: boolean
  pairs?: number
  truncated?: boolean
  conversations?: TrajectoryConversation[]
}

interface Pair {
  id: number
  human: string
  agent: string
  index: number
}

export function SessionsPage() {
  const { confirm, confirmNode } = useConfirm()
  const { push } = useToast()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const trajectory = usePolled<TrajectoryResponse>(() => api.get('/api/trajectory?limit=200'), 0)
  const memory = usePolled<MemoryResponse>(() => api.get('/api/memory', { tail: 40 }), 0)

  const pairs = useMemo<Pair[]>(() => {
    const list = trajectory.data?.conversations || []
    const out: Pair[] = []
    let pending: string | null = null
    let i = 0
    for (const item of list) {
      const text = typeof item.value === 'string' ? item.value : ''
      if (!text.trim()) continue
      if (item.from === 'human') {
        pending = text
      } else if (item.from === 'gpt' || item.from === 'assistant') {
        i += 1
        out.push({ id: i, human: pending ?? '', agent: text, index: i })
        pending = null
      }
    }
    if (pending) out.push({ id: ++i, human: pending, agent: '', index: i })
    return out.reverse()
  }, [trajectory.data])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return pairs
    return pairs.filter(
      (p) => p.human.toLowerCase().includes(q) || p.agent.toLowerCase().includes(q),
    )
  }, [pairs, query])

  const clearLog = async () => {
    const ok = await confirm(
      'Clear conversation log',
      'This rotates chatlog.jsonl into chatlog.prev.jsonl and starts a fresh transcript. Saved memory facts and skills are untouched.',
    )
    if (!ok) return
    try {
      await api.post('/api/memory', { clear_log: true })
      push('ok', 'Conversation log rotated')
      trajectory.reload()
      memory.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Clear failed')
    }
  }

  const exportLog = () => {
    const lines: string[] = []
    for (const p of [...pairs].reverse()) {
      if (p.human) lines.push(`USER: ${p.human}`)
      if (p.agent) lines.push(`AGENT: ${p.agent}`)
      lines.push('')
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'hermes-transcript.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  const loading = trajectory.loading && !trajectory.data

  return (
    <>
      <PageHeader
        title="Sessions"
        icon={<MessageSquare className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" onClick={exportLog} disabled={!pairs.length}>
              <Download className="h-3 w-3" /> Export
            </Button>
            <Button size="sm" variant="danger" onClick={() => void clearLog()}>
              <Trash2 className="h-3 w-3" /> Clear log
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Turns', value: trajectory.data?.pairs ?? pairs.length },
              { label: 'In log', value: filtered.length },
              {
                label: 'Chat log',
                value: bytes(trajectory.data ? memory.data?.log_bytes : undefined),
              },
              {
                label: 'Memory',
                value: bytes(memory.data?.memory ? memory.data.memory.length : 0),
              },
            ]}
          />

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
            <input
              className="input pl-8"
              placeholder="Search this device's conversation history…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {trajectory.error && <ErrorNote onRetry={trajectory.reload}>{trajectory.error}</ErrorNote>}

          <Panel
            title={
              <span className="flex items-center gap-1.5">
                <MessageSquare className="h-3.5 w-3.5" /> Recent conversations
              </span>
            }
          >
            {loading ? (
              <Loading />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<MessageSquare className="h-5 w-5" />}
                title={query ? 'No matching turns' : 'No conversations yet'}
                detail={
                  query
                    ? 'Try a different search term.'
                    : 'Every exchange is written to chatlog.jsonl on the device. Say hello on the Chat page and it will show up here.'
                }
                action={!query ? <Button onClick={() => navigate('/')}>Open Chat</Button> : undefined}
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {filtered.map((pair) => (
                  <li key={pair.id}>
                    <button
                      type="button"
                      onClick={() => navigate('/')}
                      className="group flex w-full items-start gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-midground/4"
                    >
                      <span className="mt-0.5 font-mono-ui text-[0.68rem] tabular-nums text-text-faint">
                        #{pair.index}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[0.83rem] text-midground">
                          {pair.human || '(no prompt)'}
                        </span>
                        {pair.agent && (
                          <span className="mt-0.5 block truncate text-[0.75rem] text-text-tertiary">
                            {pair.agent}
                          </span>
                        )}
                      </span>
                      <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-faint group-hover:text-midground" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            title="Saved memory"
            actions={
              <Chip tone="muted">{memory.data?.memory ? 'facts stored' : 'empty'}</Chip>
            }
          >
            <div className={cn('px-3.5 py-3')}>
              {memory.data?.memory ? (
                <pre className="whitespace-pre-wrap break-words font-mono-ui text-[0.75rem] leading-relaxed text-text-secondary">
                  {memory.data.memory}
                </pre>
              ) : (
                <p className="text-[0.8rem] text-text-faint">
                  No durable facts yet. The agent writes them here with the <code>mem_save</code>{' '}
                  tool — and they survive reboots.
                </p>
              )}
            </div>
          </Panel>

          {memory.data?.log_tail && memory.data.log_tail.length > 0 && (
            <p className="px-1 text-[0.7rem] text-text-faint">
              Last entry {relativeTime(Date.now() / 1000)} · {memory.data.log_tail.length} lines in
              the tail window
            </p>
          )}
        </div>
      </PageBody>
      {confirmNode}
    </>
  )
}
