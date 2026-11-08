import { useMemo } from 'react'
import { BarChart3, Cpu, Database, Gauge, Radio, RefreshCw, Zap } from 'lucide-react'
import { api } from '@/lib/api'
import { useAppData, usePolled } from '@/lib/app-data'
import { bytes, cn, heap, pct, uptime } from '@/lib/utils'
import { Button, EmptyState, ErrorNote, Loading, Panel, StatStrip } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface Stats {
  ram_free?: number
  ram_total?: number
  ram_alloc?: number
  fs_free?: number
  fs_total?: number
  fs_used?: number
  flash_size?: number
  turns_since_boot?: number
  tool_calls?: Record<string, number>
  chat_lines?: number
  mem_facts?: number
  tools_total?: number
  tools_enabled?: string[]
  rssi?: number
  cpu_freq?: number
  last_upstream_ms?: number
  mcu_temp_c?: number
  uptime_s?: number
  now?: number
  model?: string
  platform?: string
}

export function AnalyticsPage() {
  const { status } = useAppData()
  const stats = usePolled<Stats>((signal) => api.get('/api/stats', undefined, signal), 10000)

  const s = stats.data

  const toolCalls = useMemo(() => {
    const entries = Object.entries(s?.tool_calls || {}).filter(([, v]) => typeof v === 'number' && v > 0)
    return entries.sort((a, b) => (b[1] as number) - (a[1] as number))
  }, [s])

  const maxCalls = toolCalls.length ? Math.max(...toolCalls.map(([, v]) => v as number)) : 1

  const ramUsedPct = s?.ram_total ? pct((s.ram_total || 0) - (s.ram_free || 0), s.ram_total) : 0
  const fsUsedPct = s?.fs_total ? pct(s.fs_used || 0, s.fs_total) : 0

  return (
    <>
      <PageHeader
        title="Analytics"
        icon={<BarChart3 className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <Button size="sm" variant="ghost" onClick={() => stats.reload()}>
            <RefreshCw className="h-3 w-3" /> Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          {stats.error && <ErrorNote onRetry={stats.reload}>{stats.error}</ErrorNote>}

          <StatStrip
            items={[
              { label: 'Turns', value: s?.turns_since_boot ?? 0 },
              { label: 'Chat lines', value: s?.chat_lines ?? 0 },
              { label: 'Memory facts', value: s?.mem_facts ?? 0 },
              {
                label: 'Tool calls',
                value: toolCalls.reduce((sum, [, v]) => sum + (v as number), 0),
              },
            ]}
          />

          {stats.loading && !s ? (
            <Loading label="Sampling device counters…" />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              <Panel title="Memory" icon={<Cpu className="h-3.5 w-3.5" />}>
                <div className="flex flex-col gap-2 px-3.5 py-3">
                  <div className="flex items-baseline justify-between gap-2 text-[0.8rem]">
                    <span className="text-text-faint">Heap free</span>
                    <span className="font-mono-ui tabular-nums text-midground">
                      {heap(s?.ram_free)} / {heap(s?.ram_total)}
                    </span>
                  </div>
                  <Meter value={ramUsedPct} />
                  <div className="flex items-center justify-between text-[0.7rem] text-text-faint">
                    <span>{ramUsedPct}% used</span>
                    <span>{heap(s?.ram_alloc)} allocated</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 border-t border-border pt-2 text-[0.78rem]">
                    <span className="text-text-faint">Modules loaded</span>
                    <span className="font-mono-ui tabular-nums text-text-secondary">
                      {s?.tools_enabled?.length ?? 0} tools
                    </span>
                  </div>
                </div>
              </Panel>

              <Panel title="Flash" icon={<Database className="h-3.5 w-3.5" />}>
                <div className="flex flex-col gap-2 px-3.5 py-3">
                  <div className="flex items-baseline justify-between gap-2 text-[0.8rem]">
                    <span className="text-text-faint">Filesystem used</span>
                    <span className="font-mono-ui tabular-nums text-midground">
                      {bytes(s?.fs_used)} / {bytes(s?.fs_total)}
                    </span>
                  </div>
                  <Meter value={fsUsedPct} tone={fsUsedPct > 85 ? 'warning' : 'default'} />
                  <div className="flex items-center justify-between text-[0.7rem] text-text-faint">
                    <span>{fsUsedPct}% used</span>
                    <span>{bytes(s?.fs_free)} free</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 border-t border-border pt-2 text-[0.78rem]">
                    <span className="text-text-faint">Flash chip</span>
                    <span className="font-mono-ui tabular-nums text-text-secondary">
                      {bytes(s?.flash_size || s?.fs_total)}
                    </span>
                  </div>
                </div>
              </Panel>

              <Panel title="Tool usage" icon={<Zap className="h-3.5 w-3.5" />}>
                {toolCalls.length === 0 ? (
                  <EmptyState
                    icon={<Zap className="h-5 w-5" />}
                    title="No tool calls since boot"
                    detail="Counters reset when the device restarts. Ask the agent to check its status and this table fills in."
                  />
                ) : (
                  <ul className="divide-y divide-border/40 px-3.5 py-1">
                    {toolCalls.map(([name, count]) => (
                      <li key={name} className="flex items-center gap-3 py-1.5">
                        <span className="w-28 shrink-0 truncate font-mono-ui text-[0.74rem] text-text-secondary">
                          {name}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block h-1.5 w-full bg-midground/10">
                            <span
                              className="block h-full bg-midground"
                              style={{ width: `${pct(count as number, maxCalls)}%` }}
                            />
                          </span>
                        </span>
                        <span className="w-8 shrink-0 text-right font-mono-ui text-[0.72rem] tabular-nums text-text-tertiary">
                          {count as number}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel title="Link" icon={<Radio className="h-3.5 w-3.5" />}>
                <dl className="grid grid-cols-1 gap-y-1 px-3.5 py-3 text-[0.78rem]">
                  {[
                    ['SSID', status?.ssid || '—'],
                    ['IP', status?.ip || '—'],
                    ['RSSI', s?.rssi !== undefined ? `${s.rssi} dBm` : '—'],
                    ['CPU', s?.cpu_freq ? `${Math.round(s.cpu_freq / 1_000_000)} MHz` : '—'],
                    ['Upstream', s?.last_upstream_ms ? `${s.last_upstream_ms} ms` : '—'],
                    ['Uptime', uptime(s?.uptime_s ?? status?.uptime_s)],
                    ['Model', s?.model || status?.model || '—'],
                    ['Platform', s?.platform || '—'],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-baseline justify-between gap-3">
                      <dt className="text-text-faint">{label}</dt>
                      <dd className="min-w-0 truncate font-mono-ui text-text-secondary">{value}</dd>
                    </div>
                  ))}
                </dl>
              </Panel>
            </div>
          )}

          <Panel title="Thermals & load" icon={<Gauge className="h-3.5 w-3.5" />}>
            <div className="grid gap-3 px-3.5 py-3 sm:grid-cols-3">
              <Readout label="MCU temperature" value={s?.mcu_temp_c !== undefined ? `${s.mcu_temp_c.toFixed(1)} °C` : '—'} />
              <Readout label="Free heap" value={heap(status?.free_heap ?? s?.ram_free)} />
              <Readout label="Tools total" value={String(s?.tools_total ?? s?.tools_enabled?.length ?? '—')} />
            </div>
          </Panel>
        </div>
      </PageBody>
    </>
  )
}

function Meter({ value, tone = 'default' }: { value: number; tone?: 'default' | 'warning' }) {
  return (
    <div className="h-1.5 w-full bg-midground/10" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={cn('h-full transition-[width] duration-500', tone === 'warning' ? 'bg-warning' : 'bg-midground')}
        style={{ width: `${value}%` }}
      />
    </div>
  )
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-border px-3 py-2">
      <p className="label-display text-[0.6rem] tracking-[0.14em] text-text-tertiary">{label}</p>
      <p className="mt-1 font-mono-ui text-[0.95rem] tabular-nums text-midground">{value}</p>
    </div>
  )
}
