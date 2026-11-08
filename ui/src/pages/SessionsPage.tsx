import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Download,
  Loader2,
  MessageSquare,
  Plus,
  Search,
  Trash2,
} from 'lucide-react'
import { api, type MemoryResponse, type SessionsResponse } from '@/lib/api'
import { bytes, cn, relativeTime } from '@/lib/utils'
import { usePolled } from '@/lib/app-data'
import {
  Button,
  Chip,
  EmptyState,
  ErrorNote,
  Loading,
  Panel,
  StatStrip,
  useConfirm,
  useToast,
} from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

/** One conversation file on the device (opt/data/sessions/<id>.jsonl). */
interface Row {
  id: string
  title: string
  created?: number
  bytes?: number
  kind: 'web' | 'telegram'
  active: boolean
}

/** Ordering for the conversation list. Default = newest first. */
type SortKey = 'date' | 'size'

const SORT_TABS: Array<{ id: SortKey; label: string }> = [
  { id: 'date', label: 'By date' },
  { id: 'size', label: 'Size' },
]

export function SessionsPage() {
  const { confirm, confirmNode } = useConfirm()
  const { push } = useToast()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>('date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const sessions = usePolled<SessionsResponse>(() => api.get('/api/sessions'), 0)
  const memory = usePolled<MemoryResponse>(() => api.get('/api/memory', { tail: 40 }), 0)

  const rows = useMemo<Row[]>(() => {
    const list = sessions.data?.sessions || []
    return list.map((s) => ({
      id: typeof s.id === 'string' ? s.id : '',
      title: typeof s.title === 'string' && s.title ? s.title : '',
      created: typeof s.created === 'number' ? s.created : undefined,
      bytes: typeof s.bytes === 'number' ? s.bytes : undefined,
      kind: s.kind === 'telegram' ? 'telegram' : 'web',
      active: s.active === true,
    }))
  }, [sessions.data])

  /* Filter first, then order. Clicking the active tab flips the direction so
     both ends of a long list stay one click away. */
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = q ? rows.filter((r) => r.title.toLowerCase().includes(q)) : rows.slice()
    const sign = sortDir === 'desc' ? -1 : 1
    list.sort((a, b) => {
      const av = sortBy === 'size' ? a.bytes || 0 : a.created || 0
      const bv = sortBy === 'size' ? b.bytes || 0 : b.created || 0
      if (av !== bv) return (av - bv) * sign
      return (a.title || a.id).localeCompare(b.title || b.id)
    })
    return list
  }, [rows, query, sortBy, sortDir])

  const pickSort = (id: SortKey) => {
    if (id === sortBy) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
      return
    }
    setSortBy(id)
    setSortDir('desc')
  }

  const newSession = async () => {
    try {
      const res = await api.post<{ session?: string }>('/api/sessions', {})
      const sid = typeof res.session === 'string' ? res.session : ''
      sessions.reload()
      if (sid) navigate(`/?session=${encodeURIComponent(sid)}`)
      else push('ok', 'New conversation started')
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Could not start a session')
    }
  }

  const open = (id: string) => {
    if (!id) return
    navigate(`/?session=${encodeURIComponent(id)}`)
  }

  const remove = async (row: Row) => {
    if (!row.id) return
    const ok = await confirm(
      'Delete conversation',
      <>
        Removes this conversation from the device. Saved memory facts and skills are untouched.
        This cannot be undone.
        <span className="mt-2 block truncate font-mono-ui text-[0.75rem] text-text-faint">
          {row.title || '(no messages)'}
        </span>
      </>,
    )
    if (!ok) return
    setDeleting(row.id)
    try {
      await api.post('/api/sessions/delete', { id: row.id })
      push('ok', 'Conversation deleted')
      sessions.reload()
      memory.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  /* One conversation, straight from flash: /api/sessions/export streams the
     whole file (not the /api/memory tail), and a plain <a> download means the
     browser writes it to disk without holding it in JS. */
  const exportOne = (row: Row) => {
    if (!row.id) return
    const token = localStorage.getItem('esp32_token') || ''
    const url = `/api/sessions/export?id=${encodeURIComponent(row.id)}${
      token ? `&token=${encodeURIComponent(token)}` : ''
    }`
    const a = document.createElement('a')
    a.href = url
    a.download = `talaria-${row.id}.txt`
    a.click()
  }

  const loading = sessions.loading && !sessions.data
  const activeId = sessions.data?.active || memory.data?.session || ''

  return (
    <>
      <PageHeader
        title="Sessions"
        icon={<MessageSquare className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <Button size="sm" variant="primary" onClick={() => void newSession()}>
            <Plus className="h-3 w-3" /> New session
          </Button>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Conversations', value: sessions.data?.total ?? rows.length },
              { label: 'Showing', value: filtered.length },
              { label: 'Active', value: activeId ? activeId.slice(0, 12) : '—' },
              {
                label: 'Chat log',
                value: bytes(sessions.data ? memory.data?.log_bytes : undefined),
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
              placeholder="Search conversations by first message…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {sessions.error && <ErrorNote onRetry={sessions.reload}>{sessions.error}</ErrorNote>}

          <Panel
            title={
              <span className="flex items-center gap-1.5">
                <MessageSquare className="h-3.5 w-3.5" /> Conversations
              </span>
            }
            actions={
              <div className="flex items-center gap-1.5">
                <div
                  role="group"
                  aria-label="Order conversations"
                  className="flex shrink-0 items-stretch border border-border"
                >
                  {SORT_TABS.map((tab) => {
                    const active = tab.id === sortBy
                    const Arrow = sortDir === 'desc' ? ArrowDown : ArrowUp
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => pickSort(tab.id)}
                        title={
                          active
                            ? `Ordered by ${tab.label.toLowerCase()} — click to reverse`
                            : `Order by ${tab.label.toLowerCase()}`
                        }
                        className={cn(
                          'flex items-center gap-1 border-r border-border px-2 py-1 label-display text-[0.62rem] transition-colors last:border-r-0',
                          active
                            ? 'bg-midground text-background-base'
                            : 'text-text-secondary hover:bg-midground/8 hover:text-midground',
                        )}
                      >
                        {tab.label}
                        {active && <Arrow className="h-3 w-3" />}
                      </button>
                    )
                  })}
                </div>
                <Chip tone="muted">{rows.length} stored</Chip>
              </div>
            }
          >
            {loading ? (
              <Loading />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<MessageSquare className="h-5 w-5" />}
                title={query ? 'No matching conversations' : 'No conversations yet'}
                detail={
                  query
                    ? 'Try a different search term.'
                    : 'Every conversation is one file on the device. Start chatting and it appears here; New Chat on the Chat page starts another one.'
                }
                action={
                  query ? undefined : <Button onClick={() => void newSession()}>New session</Button>
                }
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {filtered.map((row) => (
                  <li key={row.id || row.title}>
                    <div className="group flex items-start gap-1 px-3.5 py-2.5 transition-colors hover:bg-midground/4">
                      <button
                        type="button"
                        onClick={() => open(row.id)}
                        className="flex min-w-0 flex-1 items-start gap-3 text-left"
                      >
                        <span className="mt-0.5 font-mono-ui text-[0.68rem] tabular-nums text-text-faint">
                          {row.active ? '●' : '○'}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span
                            className={cn(
                              'block truncate text-[0.83rem]',
                              row.active ? 'text-midground' : 'text-text-secondary',
                            )}
                          >
                            {row.title || '(no messages yet)'}
                          </span>
                          <span className="mt-0.5 flex flex-wrap items-center gap-2 text-[0.7rem] text-text-faint">
                            {row.kind === 'telegram' && <Chip tone="muted">telegram</Chip>}
                            {row.active && <span className="text-midground">active</span>}
                            <span>{relativeTime(row.created)}</span>
                            <span>· {bytes(row.bytes)}</span>
                            <span className="font-mono-ui">{row.id}</span>
                          </span>
                        </span>
                        <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-faint group-hover:text-midground" />
                      </button>
                      <button
                        type="button"
                        onClick={() => exportOne(row)}
                        disabled={!row.id || !row.bytes}
                        aria-label={`Export session ${row.title || row.id}`}
                        title="Export conversation as text"
                        className="mt-0.5 shrink-0 p-1 text-text-faint transition-colors hover:text-midground disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(row)}
                        disabled={!row.id || deleting === row.id}
                        aria-label={`Delete session ${row.title || row.id}`}
                        title="Delete conversation"
                        className="mt-0.5 shrink-0 p-1 text-text-faint transition-colors hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {deleting === row.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
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
        </div>
      </PageBody>
      {confirmNode}
    </>
  )
}
