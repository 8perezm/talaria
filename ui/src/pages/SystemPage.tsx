import { useState } from 'react'
import {
  Activity,
  AlertOctagon,
  Cpu,
  Download,
  HardDrive,
  History,
  LayoutGrid,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Thermometer,
  Wifi,
} from 'lucide-react'
import { api, type StatsResponse } from '@/lib/api'
import { useAppData, usePolled } from '@/lib/app-data'
import { bytes, cn, heap, uptime } from '@/lib/utils'
import { Button, Chip, EmptyState, ErrorNote, Field, Loading, Modal, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface Stats {
  ram_free?: number
  ram_alloc?: number
  mcu_temp_c?: number
  board?: string
  board_machine?: string
  mpy_version?: string
  mpy_thread?: string
  chip_s3?: boolean
  pins_adc?: number[]
  tools_enabled?: string[]
  tools_mask?: number
  tool_calls?: Record<string, number>
  idf_heap?: Array<{ caps: number; free: number; min_free: number; largest: number }>
  endpoint_configured?: boolean
  ap_mode?: boolean
  last_chat_ms?: number
  log_bytes?: number
  mem_bytes?: number
}

interface Doctor {
  firmware_verdict?: string
  wifi?: { connected?: boolean; ip?: string; ap_mode?: boolean }
  dns_ms?: number
  dns_ok?: boolean
  upstream_ok?: boolean
  upstream_ms?: number
  files?: Record<string, number>
  psram_ok?: boolean
  ntp_ok?: boolean
  host?: string
  heap_free?: number
  endpoint?: string
}

interface Backups {
  success?: boolean
  backups?: Array<{ name?: string; file?: string; path?: string; size?: number; ts?: number; mtime?: number }>
  max_backups?: number
  count?: number
}

export function SystemPage() {
  const { status, refreshStatus, refreshConfig } = useAppData()
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const [resetOpen, setResetOpen] = useState(false)
  const [resetWord, setResetWord] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const stats = usePolled<StatsResponse>((signal) => api.get('/api/stats', undefined, signal), 10000)
  const doctor = usePolled<Doctor>((signal) => api.get('/api/doctor', undefined, signal), 30000)
  const backups = usePolled<Backups>((signal) => api.get('/api/rollback', undefined, signal), 0)

  const s = stats.data as Stats | null

  const reboot = async () => {
    const ok = await confirm(
      'Restart the agent',
      'The device reboots. Nothing is erased — config, memory, skills and the chat log are kept. The page will reconnect on its own.',
    )
    if (!ok) return
    setBusy('reboot')
    try {
      await api.post('/api/reboot')
      push('info', 'Rebooting…')
      setTimeout(() => {
        void refreshStatus()
        void refreshConfig()
      }, 5000)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Reboot failed')
    } finally {
      setBusy(null)
    }
  }

  const downloadBackup = () => {
    const a = document.createElement('a')
    a.href = '/api/backup'
    a.download = 'hermes-device-backup.json'
    a.click()
  }

  const factoryReset = async () => {
    if (resetWord.trim().toUpperCase() !== 'RESET') return
    setBusy('reset')
    try {
      await api.post('/api/reset')
      push('info', 'Factory reset — the device is rebooting with a blank config')
      setResetOpen(false)
      setResetWord('')
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Reset failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader
        title="System"
        icon={<LayoutGrid className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => { stats.reload(); doctor.reload(); backups.reload() }}>
              <RefreshCw className="h-3 w-3" /> Refresh
            </Button>
            <Button size="sm" onClick={() => void reboot()} loading={busy === 'reboot'}>
              <RotateCw className="h-3 w-3" /> Restart
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              {
                label: 'Free heap',
                value: heap(status?.free_heap),
                tone: status?.free_heap === undefined ? 'default' : (status.free_heap || 0) > 1_000_000 ? 'success' : 'warning',
              },
              { label: 'Uptime', value: uptime(status?.uptime_s) },
              {
                label: 'WiFi',
                value: status === null ? '—' : status.wifi_connected ? 'up' : 'down',
                tone: status === null ? 'default' : status.wifi_connected ? 'success' : 'danger',
              },
              { label: 'MCU temp', value: s?.mcu_temp_c !== undefined ? `${s.mcu_temp_c.toFixed(1)}°C` : '—' },
            ]}
          />

          <div className="grid gap-3 lg:grid-cols-2">
            <Panel title="Device" icon={<Cpu className="h-3.5 w-3.5" />}>
              <dl className="grid grid-cols-1 gap-y-1 px-3.5 py-3 text-[0.78rem]">
                {[
                  ['Board', s?.board_machine || s?.board || 'ESP32'],
                  ['Firmware', s?.mpy_version || status?.firmware || 'MicroPython'],
                  ['Chip', s?.chip_s3 ? 'ESP32-S3' : 'ESP32'],
                  ['Free RAM', `${heap(s?.ram_free)} (allocated ${heap(s?.ram_alloc)})`],
                  ['Log bytes', bytes(s?.log_bytes || status?.log_bytes)],
                  ['Memory bytes', bytes(s?.mem_bytes || status?.mem_bytes)],
                  ['IP', status?.ip || '—'],
                  ['mDNS', status?.mdns || '—'],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-baseline justify-between gap-3">
                    <dt className="text-text-faint">{label}</dt>
                    <dd className="min-w-0 truncate font-mono-ui text-text-secondary">{value}</dd>
                  </div>
                ))}
              </dl>
            </Panel>

            <Panel
              title="Health"
              icon={<ShieldCheck className="h-3.5 w-3.5" />}
              actions={
                doctor.data?.firmware_verdict ? (
                  <Chip tone={doctor.data.firmware_verdict.includes('SPIRAM') ? 'success' : 'warning'}>
                    {doctor.data.firmware_verdict}
                  </Chip>
                ) : undefined
              }
            >
              {doctor.loading && !doctor.data ? (
                <Loading label="Running diagnostics…" />
              ) : doctor.error ? (
                <div className="px-3.5 py-3">
                  <ErrorNote onRetry={doctor.reload}>{doctor.error}</ErrorNote>
                </div>
              ) : (
                <ul className="divide-y divide-border/50 px-3.5 text-[0.78rem]">
                  {[
                    ['WiFi', doctor.data?.wifi?.connected, doctor.data?.wifi?.ip || 'not connected'],
                    ['DNS', doctor.data?.dns_ok, `${doctor.data?.dns_ms ?? '—'} ms`],
                    ['Upstream', doctor.data?.upstream_ok, `${doctor.data?.upstream_ms ?? '—'} ms · ${doctor.data?.host || ''}`],
                    ['PSRAM', doctor.data?.psram_ok, doctor.data?.psram_ok ? 'octal, healthy' : 'unavailable'],
                    ['NTP', doctor.data?.ntp_ok, doctor.data?.ntp_ok ? 'synced' : 'not synced'],
                  ].map(([label, ok, detail]) => (
                    <li key={String(label)} className="flex items-center gap-2 py-1.5">
                      <span
                        className={cn(
                          'dot',
                          ok ? 'text-success' : 'text-destructive',
                        )}
                      />
                      <span className="w-20 shrink-0 text-text-faint">{label}</span>
                      <span className="min-w-0 flex-1 truncate font-mono-ui text-text-secondary">
                        {String(detail)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Runtime" icon={<Activity className="h-3.5 w-3.5" />}>
              <div className="flex flex-col gap-2 px-3.5 py-3 text-[0.78rem]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-text-faint">Tools enabled</span>
                  <span className="font-mono-ui tabular-nums text-text-secondary">
                    {s?.tools_enabled?.length ?? '—'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-text-faint">Last chat</span>
                  <span className="font-mono-ui tabular-nums text-text-secondary">
                    {s?.last_chat_ms ? `${s.last_chat_ms} ms` : 'idle'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-text-faint">AP mode</span>
                  <Chip tone={s?.ap_mode ? 'warning' : 'muted'}>{s?.ap_mode ? 'on' : 'off'}</Chip>
                </div>
                {s?.idf_heap && s.idf_heap.length > 0 && (
                  <div className="mt-1 border-t border-border pt-2">
                    <p className="mb-1 label-display text-[0.6rem] tracking-[0.14em] text-text-faint">
                      IDF heap regions
                    </p>
                    {s.idf_heap.slice(0, 4).map((region, index) => (
                      <div key={index} className="flex items-center justify-between gap-2">
                        <span className="text-text-faint">caps 0x{region.caps.toString(16)}</span>
                        <span className="font-mono-ui tabular-nums text-text-secondary">
                          {heap(region.free)} free · {heap(region.largest)} largest
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {s?.pins_adc && (
                  <p className="mt-1 text-[0.7rem] leading-relaxed text-text-faint">
                    <Thermometer className="mr-1 inline h-3 w-3" />
                    ADC pins: {s.pins_adc.join(', ')}
                  </p>
                )}
              </div>
            </Panel>

            <Panel
              title="Checkpoints"
              icon={<History className="h-3.5 w-3.5" />}
              actions={
                backups.data?.backups?.length ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await api.post('/api/rollback', { op: 'prune', keep: 4 })
                        push('ok', 'Old checkpoints pruned')
                        backups.reload()
                      } catch (err) {
                        push('err', err instanceof Error ? err.message : 'Prune failed')
                      }
                    }}
                  >
                    Prune
                  </Button>
                ) : undefined
              }
            >
              {backups.loading && !backups.data ? (
                <Loading label="Listing checkpoints…" />
              ) : (backups.data?.backups?.length || 0) === 0 ? (
                <EmptyState
                  icon={<History className="h-5 w-5" />}
                  title="No checkpoints"
                  detail="Every file write through the Files editor snapshots the previous version here, so a bad edit is one click from recovery."
                />
              ) : (
                <ul className="divide-y divide-border/50">
                  {backups.data?.backups?.map((b, index) => (
                    <li key={index} className="flex items-center gap-2 px-3.5 py-2 text-[0.76rem]">
                      <History className="h-3 w-3 shrink-0 text-text-faint" />
                      <span className="min-w-0 flex-1 truncate font-mono-ui text-text-secondary">
                        {b.file || b.name || b.path || `checkpoint ${index + 1}`}
                      </span>
                      <span className="shrink-0 font-mono-ui text-[0.7rem] text-text-faint">
                        {b.size ? bytes(b.size) : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <Panel title="Data & firmware" icon={<HardDrive className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-3 px-3.5 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[0.8rem] text-text-secondary">Download a full backup</p>
                  <p className="text-[0.72rem] text-text-faint">
                    Config, memory, skills and cron — API keys are redacted to masked shapes.
                  </p>
                </div>
                <Button size="sm" onClick={downloadBackup}>
                  <Download className="h-3 w-3" /> Backup JSON
                </Button>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
                <div className="min-w-0">
                  <p className="text-[0.8rem] text-text-secondary">Firmware & UI update</p>
                  <p className="text-[0.72rem] text-text-faint">
                    Upload panel files, re-flash MicroPython, or push a new bundle.
                  </p>
                </div>
                <a href="/update" className="btn btn-sm">
                  Open Update
                </a>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-destructive/40 pt-2">
                <div className="min-w-0">
                  <p className="text-[0.8rem] text-destructive">Factory reset</p>
                  <p className="text-[0.72rem] text-text-faint">
                    Deletes config.yaml, memory and the chat log, then reboots. The device comes back
                    in setup mode.
                  </p>
                </div>
                <Button size="sm" variant="danger" onClick={() => setResetOpen(true)}>
                  <AlertOctagon className="h-3 w-3" /> Reset
                </Button>
              </div>
            </div>
          </Panel>

          <Panel title="Connectivity" icon={<Wifi className="h-3.5 w-3.5" />}>
            <div className="flex flex-wrap items-center gap-2 px-3.5 py-3 text-[0.78rem]">
              <Chip
                tone={status === null ? 'muted' : status.wifi_connected ? 'success' : 'danger'}
                dot={status !== null}
              >
                {status === null ? 'reading…' : status.wifi_connected ? status.ssid || 'connected' : 'disconnected'}
              </Chip>
              <Chip tone="muted">{status?.ip || 'no ip'}</Chip>
              <Chip tone={status === null ? 'muted' : status.endpoint_configured ? 'success' : 'danger'}>
                {status === null ? 'endpoint …' : status.endpoint_configured ? 'endpoint set' : 'endpoint missing'}
              </Chip>
              <a href="/wifi" className="btn btn-sm ml-auto">
                WiFi settings
              </a>
            </div>
          </Panel>
        </div>
      </PageBody>

      <Modal
        open={resetOpen}
        title="Factory reset"
        onClose={() => setResetOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setResetOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={busy === 'reset'}
              disabled={resetWord.trim().toUpperCase() !== 'RESET'}
              onClick={() => void factoryReset()}
            >
              Wipe &amp; reboot
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-[0.82rem] leading-relaxed text-text-secondary">
            This deletes <code>config.yaml</code> (WiFi + endpoint + API key + auth token),{' '}
            <code>memory.txt</code>, <code>chatlog.jsonl</code> and the skills directory. It is
            <strong className="text-destructive"> not</strong> the same as Restart.
          </p>
          <Field label="Type RESET to confirm">
            <input
              className="input font-mono-ui"
              value={resetWord}
              onChange={(e) => setResetWord(e.target.value)}
              placeholder="RESET"
              autoFocus
            />
          </Field>
        </div>
      </Modal>
      {confirmNode}
    </>
  )
}
