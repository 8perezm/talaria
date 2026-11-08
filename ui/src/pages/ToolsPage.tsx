import { useMemo, useState } from 'react'
import { Check, Search, ToggleLeft, ToggleRight, Wrench } from 'lucide-react'
import { api, type ToolsResponse } from '@/lib/api'
import { usePolled } from '@/lib/app-data'
import { cn } from '@/lib/utils'
import { Button, Chip, EmptyState, ErrorNote, Loading, Panel, StatStrip, Toggle, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

export function ToolsPage() {
  const { push } = useToast()
  const [query, setQuery] = useState('')
  const [saving, setSaving] = useState(false)

  const tools = usePolled<ToolsResponse>((signal) => api.get('/api/tools', undefined, signal), 0)

  const list = tools.data?.tools || []

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q
      ? list.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            (t.label || '').toLowerCase().includes(q) ||
            (t.description || '').toLowerCase().includes(q),
        )
      : list
    const map = new Map<string, typeof list>()
    for (const tool of filtered) {
      const key = tool.toolset || 'other'
      const bucket = map.get(key) || []
      bucket.push(tool)
      map.set(key, bucket)
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [list, query])

  const enabledCount = list.filter((t) => t.enabled).length

  const setEnabled = async (name: string, enabled: boolean) => {
    const nextEnabled = list
      .map((t) => (t.name === name ? { ...t, enabled } : t))
      .filter((t) => t.enabled)
      .map((t) => t.name)
    setSaving(true)
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/tools', {
        enabled: nextEnabled,
      })
      if (res.error) throw new Error(res.error)
      tools.setData((prev) =>
        prev ? { ...prev, tools: prev.tools.map((t) => (t.name === name ? { ...t, enabled } : t)) } : prev,
      )
      push('ok', `${name} ${enabled ? 'enabled' : 'disabled'}`)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  const setAll = async (enabled: boolean) => {
    setSaving(true)
    try {
      const names = enabled ? list.map((t) => t.name) : []
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/tools', { enabled: names })
      if (res.error) throw new Error(res.error)
      tools.reload()
      push('ok', enabled ? 'All tools enabled' : 'All tools disabled')
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Tools"
        icon={<Wrench className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => void setAll(true)}>
              <ToggleRight className="h-3 w-3" /> Enable all
            </Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => void setAll(false)}>
              <ToggleLeft className="h-3 w-3" /> Disable all
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Registered', value: list.length },
              { label: 'Enabled', value: enabledCount, tone: enabledCount ? 'success' : 'warning' },
              { label: 'Toolsets', value: grouped.length },
              { label: 'Mask', value: tools.data?.mask ?? '—' },
            ]}
          />

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
            <input
              className="input pl-8"
              placeholder="Filter tools by name, label or description…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {tools.error && <ErrorNote onRetry={tools.reload}>{tools.error}</ErrorNote>}

          {tools.loading && !tools.data ? (
            <Loading label="Reading tool registry…" />
          ) : grouped.length === 0 ? (
            <Panel>
              <EmptyState
                icon={<Wrench className="h-5 w-5" />}
                title={query ? 'No tools match' : 'No tools registered'}
                detail={query ? 'Clear the filter to see everything.' : undefined}
              />
            </Panel>
          ) : (
            grouped.map(([toolset, items]) => (
              <Panel
                key={toolset}
                title={toolset}
                icon={<Wrench className="h-3.5 w-3.5" />}
                actions={
                  <Chip tone="muted">
                    {items.filter((t) => t.enabled).length}/{items.length}
                  </Chip>
                }
              >
                <ul className="divide-y divide-border/50">
                  {items.map((tool) => (
                    <li
                      key={tool.name}
                      className="flex items-start gap-3 px-3.5 py-2.5 transition-colors hover:bg-midground/3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-mono-ui text-[0.8rem] text-midground">{tool.name}</span>
                          {tool.label && (
                            <span className="truncate text-[0.72rem] text-text-tertiary">
                              {tool.label}
                            </span>
                          )}
                          {tool.default_off && <Chip tone="muted">opt-in</Chip>}
                          {tool.enabled && (
                            <Check className="h-3 w-3 text-success" aria-label="enabled" />
                          )}
                        </div>
                        {tool.description && (
                          <p className="mt-0.5 line-clamp-2 text-[0.74rem] leading-relaxed text-text-faint">
                            {tool.description}
                          </p>
                        )}
                      </div>
                      <Toggle
                        checked={!!tool.enabled}
                        onChange={(v) => void setEnabled(tool.name, v)}
                        label={`Toggle ${tool.name}`}
                      />
                    </li>
                  ))}
                </ul>
              </Panel>
            ))
          )}

          <p className={cn('px-1 text-[0.7rem] leading-relaxed text-text-faint')}>
            Enabled tools are described to the model in the system prompt and may be called during a
            turn. Disabling one removes it from the prompt entirely — the same behaviour as the
            upstream toolset switches.
          </p>
        </div>
      </PageBody>
    </>
  )
}
