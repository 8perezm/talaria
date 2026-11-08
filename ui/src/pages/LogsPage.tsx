import { useMemo, useState } from 'react'
import { FileText, Search, Trash2, Pause, Play, RefreshCw, Download } from 'lucide-react'
import { api, type LogsResponse } from '@/lib/api'
import { usePolled } from '@/lib/app-data'
import { cn } from '@/lib/utils'
import { Button, Chip, EmptyState, ErrorNote, Loading, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

export function LogsPage() {
  const { confirm, confirmNode } = useConfirm()
  const { push } = useToast()
  const [query, setQuery] = useState('')
  const [paused, setPaused] = useState(false)
  const [expanded, setExpanded] = useState(true)

  const logs = usePolled<LogsResponse>(
    (signal) => api.get('/api/logs', { limit: 400 }, signal),
    paused ? 0 : 3000,
  )

  const entries = useMemo(() => {
    const list = logs.data?.entries || []
    const q = query.trim().toLowerCase()
    if (!q) return list
    return list.filter((e) => e.msg.toLowerCase().includes(q))
  }, [logs.data, query])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(entries.map((e) => e.msg).join('\n'))
      push('ok', 'Copied visible log')
    } catch {
      push('err', 'Clipboard unavailable')
    }
  }

  const download = () => {
    const blob = new Blob([entries.map((e) => e.msg).join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'hermes-device.log'
    a.click()
    URL.revokeObjectURL(url)
  }

  const clear = async () => {
    const ok = await confirm('Clear device log', 'The in-RAM ring buffer is emptied. This does not touch chatlog.jsonl or memory.txt.')
    if (!ok) return
    try {
      await api.post('/api/logs/clear')
      push('ok', 'Log buffer cleared')
      logs.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Clear failed')
    }
  }

  return (
    <>
      <PageHeader
        title="Logs"
        icon={<FileText className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => setPaused((v) => !v)}>
              {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
              {paused ? 'Resume' : 'Pause'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => logs.reload()}>
              <RefreshCw className="h-3 w-3" /> Reload
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void copy()}>
              Copy
            </Button>
            <Button size="sm" variant="ghost" onClick={download}>
              <Download className="h-3 w-3" /> Save
            </Button>
            <Button size="sm" variant="danger" onClick={() => void clear()}>
              <Trash2 className="h-3 w-3" /> Clear
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Entries', value: logs.data?.count ?? entries.length },
              { label: 'Last seq', value: logs.data?.seq ?? '—' },
              { label: 'Filter', value: query ? `${entries.length} match` : 'off' },
              { label: 'Tail', value: paused ? 'paused' : 'live', tone: paused ? 'warning' : 'success' },
            ]}
          />

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
            <input
              className="input pl-8 font-mono-ui text-[0.78rem]"
              placeholder="Filter log lines…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {logs.error && <ErrorNote onRetry={logs.reload}>{logs.error}</ErrorNote>}

          <Panel
            title="Device console"
            actions={
              <>
                <Chip tone={paused ? 'warning' : 'success'} dot>
                  {paused ? 'paused' : 'streaming'}
                </Chip>
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="text-[0.65rem] text-text-tertiary hover:text-midground"
                >
                  {expanded ? 'compact' : 'expand'}
                </button>
              </>
            }
          >
            {logs.loading && !logs.data ? (
              <Loading label="Reading device log…" />
            ) : entries.length === 0 ? (
              <EmptyState
                icon={<FileText className="h-5 w-5" />}
                title={query ? 'No lines match' : 'Log buffer is empty'}
                detail={
                  query
                    ? 'Clear the filter to see all lines.'
                    : 'The boot banner and every agent event land here once the device has run.'
                }
              />
            ) : (
              <div className="max-h-[60vh] overflow-y-auto">
                <ol className="divide-y divide-border/40">
                  {entries.map((entry) => (
                    <li
                      key={entry.seq}
                      className={cn(
                        'flex items-start gap-3 px-3.5',
                        expanded ? 'py-2' : 'py-1',
                      )}
                    >
                      <span className="w-9 shrink-0 select-none text-right font-mono-ui text-[0.66rem] tabular-nums text-text-faint">
                        {entry.seq}
                      </span>
                      <span
                        className={cn(
                          'min-w-0 flex-1 whitespace-pre-wrap break-words font-mono-ui leading-relaxed',
                          expanded ? 'text-[0.75rem]' : 'text-[0.7rem]',
                          /error|fail|traceback/i.test(entry.msg)
                            ? 'text-destructive'
                            : /warn/i.test(entry.msg)
                              ? 'text-warning'
                              : 'text-text-secondary',
                        )}
                      >
                        {entry.msg}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </Panel>
        </div>
      </PageBody>
      {confirmNode}
    </>
  )
}
