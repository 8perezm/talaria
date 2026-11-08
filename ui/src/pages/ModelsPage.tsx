import { useMemo, useState } from 'react'
import { Check, Cpu, RefreshCw, Search, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { usePolled, useAppData } from '@/lib/app-data'
import { cn } from '@/lib/utils'
import { Button, Chip, EmptyState, ErrorNote, Field, Loading, Modal, Panel, StatStrip, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface ModelsResponse {
  models?: Array<{ id: string }>
  count?: number
  error?: string
}

export function ModelsPage() {
  const { status, config, refreshStatus, refreshConfig } = useAppData()
  const { push } = useToast()
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [manual, setManual] = useState('')

  const models = usePolled<ModelsResponse>(() => api.get('/api/models'), 0)

  const list = useMemo(() => {
    const items = models.data?.models || []
    const q = query.trim().toLowerCase()
    const filtered = q ? items.filter((m) => m.id.toLowerCase().includes(q)) : items
    return filtered.slice(0, 400)
  }, [models.data, query])

  const current = status?.model || config?.model || ''

  const selectModel = async (id: string) => {
    setBusy(id)
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/config', { model: id })
      if (res.error) throw new Error(res.error)
      push('ok', `Model set to ${id}`)
      await refreshStatus()
      await refreshConfig()
      setManualOpen(false)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Model switch failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Models"
        icon={<Cpu className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => models.reload()}>
              <RefreshCw className="h-3 w-3" /> Refresh
            </Button>
            <Button size="sm" onClick={() => setManualOpen(true)}>
              <Sparkles className="h-3 w-3" /> Set manually
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Available', value: models.data?.count ?? models.data?.models?.length ?? 0 },
              { label: 'In view', value: list.length },
              { label: 'Endpoint', value: config?.endpoint ? 'configured' : 'missing', tone: config?.endpoint ? 'success' : 'danger' },
              { label: 'API key', value: config?.api_key_masked || 'none', tone: config?.api_key_masked ? 'success' : 'warning' },
            ]}
          />

          <Panel title="Active model" icon={<Cpu className="h-3.5 w-3.5" />}>
            <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-3">
              <div className="min-w-0">
                <p className="truncate font-mono-ui text-[0.9rem] text-midground">{current || 'No model set'}</p>
                <p className="mt-0.5 truncate text-[0.72rem] text-text-faint">
                  {config?.endpoint || 'endpoint not configured'}
                </p>
              </div>
              <Chip tone={current ? 'success' : 'danger'} dot>
                {current ? 'ready' : 'unset'}
              </Chip>
            </div>
          </Panel>

          {models.error && (
            <ErrorNote onRetry={() => models.reload()}>
              {models.error} — the model list needs a reachable endpoint and API key.
            </ErrorNote>
          )}

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
            <input
              className="input pl-8 font-mono-ui text-[0.78rem]"
              placeholder="Filter models…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <Panel title="Catalogue" icon={<Cpu className="h-3.5 w-3.5" />}>
            {models.loading && !models.data ? (
              <Loading label="Asking the endpoint for its catalogue…" />
            ) : list.length === 0 ? (
              <EmptyState
                icon={<Cpu className="h-5 w-5" />}
                title={models.error ? 'Catalogue unavailable' : 'No models returned'}
                detail={
                  models.error
                    ? 'Fix the endpoint or API key in Config, then refresh.'
                    : 'The provider returned an empty list. You can still set a model id manually.'
                }
                action={<Button onClick={() => setManualOpen(true)}>Set manually</Button>}
              />
            ) : (
              <ul className="max-h-[52vh] divide-y divide-border/50 overflow-y-auto">
                {list.map((model) => {
                  const active = model.id === current
                  return (
                    <li key={model.id}>
                      <button
                        type="button"
                        onClick={() => void selectModel(model.id)}
                        disabled={busy !== null}
                        className={cn(
                          'flex w-full items-center gap-2 px-3.5 py-2 text-left transition-colors',
                          active ? 'bg-midground/6' : 'hover:bg-midground/4',
                        )}
                      >
                        {active ? (
                          <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                        ) : (
                          <span className="h-3.5 w-3.5 shrink-0" />
                        )}
                        <span
                          className={cn(
                            'min-w-0 flex-1 truncate font-mono-ui text-[0.78rem]',
                            active ? 'text-midground' : 'text-text-secondary',
                          )}
                        >
                          {model.id}
                        </span>
                        {busy === model.id && <Chip tone="warning">switching</Chip>}
                        {active && <Chip tone="success">active</Chip>}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Panel>
        </div>
      </PageBody>

      <Modal
        open={manualOpen}
        title="Set model id"
        onClose={() => setManualOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setManualOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!manual.trim()}
              onClick={() => void selectModel(manual.trim())}
            >
              Apply
            </Button>
          </>
        }
      >
        <Field label="Model id" hint="Exact id the endpoint expects, e.g. deepseek-ai/DeepSeek-V4.1-Flash">
          <input
            className="input font-mono-ui"
            autoFocus
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder="provider/model"
          />
        </Field>
      </Modal>
    </>
  )
}
