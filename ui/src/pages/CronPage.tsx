import { useMemo, useState } from 'react'
import { Clock, Pause, Play, Plus, Trash2, Zap, Pencil } from 'lucide-react'
import { api } from '@/lib/api'
import { usePolled } from '@/lib/app-data'
import { cn, relativeTime } from '@/lib/utils'
import { Button, Chip, EmptyState, ErrorNote, Field, Loading, Modal, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface CronJob {
  id: string
  prompt: string
  every_s: number
  next_run: number | null
  enabled: boolean
  deliver: string
  webhook_url?: string
  skills?: string[]
  created?: number
}

interface CronResponse {
  success?: boolean
  jobs: CronJob[]
  count?: number
  max_jobs?: number
  error?: string
}

const PRESETS = [
  { label: 'every 5 min', seconds: 300 },
  { label: 'every 15 min', seconds: 900 },
  { label: 'hourly', seconds: 3600 },
  { label: 'every 6 h', seconds: 21600 },
  { label: 'daily', seconds: 86400 },
]

function everyLabel(seconds: number): string {
  if (seconds % 86400 === 0) return `every ${seconds / 86400}d`
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`
  if (seconds % 60 === 0) return `every ${seconds / 60}m`
  return `every ${seconds}s`
}

function nextIn(next: number | null): string {
  if (!next) return '—'
  const now = Date.now() / 1000
  let ts = next
  if (next < 1_000_000_000) ts = next + 946_684_800
  const diff = Math.round(ts - now)
  if (diff <= 0) return 'due now'
  if (diff < 60) return `in ${diff}s`
  if (diff < 3600) return `in ${Math.round(diff / 60)}m`
  if (diff < 86400) return `in ${Math.round(diff / 3600)}h`
  return `in ${Math.round(diff / 86400)}d`
}

export function CronPage() {
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<CronJob | null>(null)
  const [prompt, setPrompt] = useState('')
  const [every, setEvery] = useState(3600)
  const [deliver, setDeliver] = useState('log')
  const [webhook, setWebhook] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const cron = usePolled<CronResponse>((signal) => api.get('/api/cron', undefined, signal), 8000)

  const jobs = useMemo(() => cron.data?.jobs || [], [cron.data])
  const active = jobs.filter((j) => j.enabled).length

  const openNew = () => {
    setEditing(null)
    setPrompt('')
    setEvery(3600)
    setDeliver('log')
    setWebhook('')
    setEditorOpen(true)
  }

  const openEdit = (job: CronJob) => {
    setEditing(job)
    setPrompt(job.prompt || '')
    setEvery(job.every_s || 3600)
    setDeliver(job.deliver || 'log')
    setWebhook(job.webhook_url || '')
    setEditorOpen(true)
  }

  const save = async () => {
    if (!prompt.trim()) return
    setBusy('save')
    try {
      const body = editing
        ? { op: 'edit', id: editing.id, prompt: prompt.trim(), every_s: every, deliver, webhook_url: webhook }
        : { op: 'add', prompt: prompt.trim(), every_s: every, deliver, webhook_url: webhook }
      const res = await api.post<{ success?: boolean; error?: string }>('/api/cron', body)
      if (!res.success) throw new Error(res.error || 'cron rejected the job')
      push('ok', editing ? 'Job updated' : 'Job scheduled')
      setEditorOpen(false)
      cron.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(null)
    }
  }

  const act = async (job: CronJob, op: 'pause' | 'resume' | 'remove' | 'run_now') => {
    if (op === 'remove') {
      const ok = await confirm('Delete job', `"${job.prompt.slice(0, 90)}" will stop running and be removed.`)
      if (!ok) return
    }
    setBusy(`${op}:${job.id}`)
    try {
      const res = await api.post<{ success?: boolean; error?: string }>('/api/cron', { op, id: job.id })
      if (!res.success) throw new Error(res.error || `${op} failed`)
      push('ok', `${op.replace('_', ' ')} ok`)
      cron.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : `${op} failed`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Cron"
        icon={<Clock className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <Button size="sm" variant="primary" onClick={openNew}>
            <Plus className="h-3 w-3" /> New job
          </Button>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Jobs', value: jobs.length },
              { label: 'Active', value: active, tone: active ? 'success' : 'warning' },
              { label: 'Capacity', value: cron.data?.max_jobs ?? '—' },
              { label: 'Next', value: jobs.length ? nextIn(jobs[0].next_run) : '—' },
            ]}
          />

          {cron.error && <ErrorNote onRetry={cron.reload}>{cron.error}</ErrorNote>}

          <Panel title="Scheduled jobs" icon={<Clock className="h-3.5 w-3.5" />}>
            {cron.loading && !cron.data ? (
              <Loading label="Reading schedule…" />
            ) : jobs.length === 0 ? (
              <EmptyState
                icon={<Clock className="h-5 w-5" />}
                title="No scheduled jobs"
                detail="Cron jobs run unattended: the agent wakes on an interval, runs a prompt, and delivers the result to the log or a webhook."
                action={<Button onClick={openNew}>Create the first job</Button>}
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {jobs.map((job) => (
                  <li key={job.id} className="flex flex-wrap items-start gap-3 px-3.5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Chip tone={job.enabled ? 'success' : 'muted'} dot>
                          {job.enabled ? 'active' : 'paused'}
                        </Chip>
                        <Chip tone="muted">{everyLabel(job.every_s)}</Chip>
                        <Chip tone="muted">→ {job.deliver}</Chip>
                        <span className="font-mono-ui text-[0.66rem] text-text-faint">{job.id}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-[0.82rem] leading-relaxed text-midground">
                        {job.prompt}
                      </p>
                      <p className="mt-0.5 text-[0.7rem] text-text-faint">
                        next {nextIn(job.next_run)}
                        {job.created ? ` · created ${relativeTime(job.created)}` : ''}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        title="Run now"
                        aria-label="Run now"
                        disabled={busy !== null}
                        onClick={() => void act(job, 'run_now')}
                        className="p-1.5 text-text-tertiary hover:text-success disabled:opacity-40"
                      >
                        <Zap className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={job.enabled ? 'Pause' : 'Resume'}
                        aria-label={job.enabled ? 'Pause' : 'Resume'}
                        disabled={busy !== null}
                        onClick={() => void act(job, job.enabled ? 'pause' : 'resume')}
                        className="p-1.5 text-text-tertiary hover:text-midground disabled:opacity-40"
                      >
                        {job.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        type="button"
                        title="Edit"
                        aria-label="Edit"
                        onClick={() => openEdit(job)}
                        className="p-1.5 text-text-tertiary hover:text-midground"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        aria-label="Delete"
                        disabled={busy !== null}
                        onClick={() => void act(job, 'remove')}
                        className="p-1.5 text-text-tertiary hover:text-destructive disabled:opacity-40"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <p className={cn('px-1 text-[0.7rem] leading-relaxed text-text-faint')}>
            Delivery <code>log</code> writes the reply to the device log; <code>webhook</code> POSTs it
            to a URL you provide. Jobs survive reboots because they live in <code>cron.json</code>.
          </p>
        </div>
      </PageBody>

      <Modal
        open={editorOpen}
        title={editing ? 'Edit job' : 'New job'}
        onClose={() => setEditorOpen(false)}
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditorOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy === 'save'} disabled={!prompt.trim()} onClick={() => void save()}>
              {editing ? 'Save' : 'Schedule'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Prompt" hint="Sent to the model verbatim when the job fires.">
            <textarea
              className="input min-h-[5rem] resize-y"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Summarise today's device log and report anything unusual."
            />
          </Field>
          <Field label="Interval">
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((preset) => (
                <button
                  key={preset.seconds}
                  type="button"
                  onClick={() => setEvery(preset.seconds)}
                  className={cn(
                    'border px-2 py-1 text-[0.68rem] uppercase tracking-[0.08em]',
                    every === preset.seconds
                      ? 'border-midground text-midground'
                      : 'border-border text-text-tertiary hover:text-midground',
                  )}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Delivery">
              <select className="input" value={deliver} onChange={(e) => setDeliver(e.target.value)}>
                <option value="log">log</option>
                <option value="webhook">webhook</option>
              </select>
            </Field>
            {deliver === 'webhook' && (
              <Field label="Webhook URL">
                <input
                  className="input font-mono-ui text-[0.76rem]"
                  value={webhook}
                  onChange={(e) => setWebhook(e.target.value)}
                  placeholder="https://example.com/hook"
                />
              </Field>
            )}
          </div>
        </div>
      </Modal>
      {confirmNode}
    </>
  )
}
