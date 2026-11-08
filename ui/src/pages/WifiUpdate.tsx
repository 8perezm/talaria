import { useEffect, useState } from 'react'
import { Download, RefreshCw, RotateCw, UploadCloud, Wifi } from 'lucide-react'
import { api, getToken } from '@/lib/api'
import { useAppData } from '@/lib/app-data'
import { bytes } from '@/lib/utils'
import { Button, Chip, Field, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

/* ------------------------------------------------------------------ */
/* WiFi                                                                */
/* ------------------------------------------------------------------ */

interface ScanNetwork {
  ssid: string
  rssi?: number
  auth?: number
}

export function WifiPage() {
  const { status, config, refreshStatus } = useAppData()
  const { push } = useToast()
  const [ssid, setSsid] = useState('')
  const [password, setPassword] = useState('')
  const [scanning, setScanning] = useState(false)
  const [networks, setNetworks] = useState<ScanNetwork[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (config?.wifi_ssid) setSsid((v) => v || config.wifi_ssid || '')
  }, [config])

  const scan = async () => {
    setScanning(true)
    try {
      const res = await api.get<{ networks?: ScanNetwork[]; error?: string }>('/api/scan')
      if (res.error) throw new Error(res.error)
      setNetworks(res.networks || [])
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const connect = async () => {
    if (!ssid.trim()) return
    setBusy(true)
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/wifi', {
        ssid: ssid.trim(),
        password,
      })
      if (res.error) throw new Error(res.error)
      push('info', 'Saved — the device is rebooting onto the new network')
      setTimeout(() => void refreshStatus(), 6000)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Connect failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="WiFi"
        icon={<Wifi className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <Button size="sm" variant="ghost" loading={scanning} onClick={() => void scan()}>
            <RefreshCw className="h-3 w-3" /> Scan
          </Button>
        }
      />
      <PageBody>
        <div className="flex max-w-3xl flex-col gap-3">
          <StatStrip
            items={[
              { label: 'State', value: status?.wifi_connected ? 'connected' : 'down', tone: status?.wifi_connected ? 'success' : 'danger' },
              { label: 'SSID', value: status?.ssid || '—' },
              { label: 'IP', value: status?.ip || '—' },
              { label: 'AP mode', value: status?.ap_mode ? 'on' : 'off', tone: status?.ap_mode ? 'warning' : 'default' },
            ]}
          />

          <Panel title="Nearby networks" icon={<Wifi className="h-3.5 w-3.5" />}>
            {networks.length === 0 ? (
              <div className="px-3.5 py-4 text-center text-[0.8rem] text-text-faint">
                Press <span className="text-text-secondary">Scan</span> to list visible access points.
              </div>
            ) : (
              <ul className="divide-y divide-border/50">
                {networks
                  .filter((n) => n.ssid)
                  .sort((a, b) => (b.rssi || -999) - (a.rssi || -999))
                  .map((n) => (
                    <li key={n.ssid}>
                      <button
                        type="button"
                        onClick={() => setSsid(n.ssid)}
                        className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[0.8rem] hover:bg-midground/5"
                      >
                        <Wifi className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
                        <span className="min-w-0 flex-1 truncate">{n.ssid}</span>
                        {n.auth === 0 && <Chip tone="warning">open</Chip>}
                        <span className="font-mono-ui text-[0.7rem] tabular-nums text-text-faint">
                          {n.rssi} dBm
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </Panel>

          <Panel title="Connect" icon={<Wifi className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-3 px-3.5 py-3">
              <Field label="SSID">
                <input className="input" value={ssid} onChange={(e) => setSsid(e.target.value)} />
              </Field>
              <Field label="Password" hint="Leave blank for an open network.">
                <input
                  className="input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="off"
                />
              </Field>
              <div className="flex justify-end">
                <Button variant="primary" loading={busy} disabled={!ssid.trim()} onClick={() => void connect()}>
                  Save &amp; reboot
                </Button>
              </div>
            </div>
          </Panel>
        </div>
      </PageBody>
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Update                                                              */
/* ------------------------------------------------------------------ */

export function UpdatePage() {
  const { status, refreshStatus } = useAppData()
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<string>('')

  const reboot = async () => {
    const ok = await confirm('Restart the agent', 'The device reboots and keeps all configuration.')
    if (!ok) return
    try {
      await api.post('/api/reboot')
      push('info', 'Rebooting…')
      setTimeout(() => void refreshStatus(), 5000)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Reboot failed')
    }
  }

  const upload = async () => {
    if (files.length === 0) return
    setBusy(true)
    try {
      for (const file of files) {
        setProgress(`Uploading ${file.name}…`)
        const form = new FormData()
        form.append('firmware', file)
        const headers: Record<string, string> = {}
        const token = getToken()
        if (token) headers.Authorization = `Bearer ${token}`
        const res = await fetch('/update', { method: 'POST', body: form, headers })
        const text = await res.text()
        if (!res.ok) throw new Error(text || `HTTP ${res.status}`)
      }
      push('ok', 'Upload complete — the device is rebooting')
      setFiles([])
      setProgress('')
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Upload failed')
      setProgress('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Update"
        icon={<UploadCloud className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <Button size="sm" onClick={() => void reboot()}>
            <RotateCw className="h-3 w-3" /> Restart
          </Button>
        }
      />
      <PageBody>
        <div className="flex max-w-3xl flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Firmware', value: status?.firmware || 'MicroPython' },
              { label: 'Free heap', value: bytes(status?.free_heap) },
              { label: 'Filesystem', value: status?.fs_ok ? 'ok' : 'unavailable', tone: status?.fs_ok ? 'success' : 'danger' },
              { label: 'Uptime', value: `${status?.uptime_s ?? 0}s` },
            ]}
          />

          <Panel title="Upload files" icon={<UploadCloud className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-3 px-3.5 py-3">
              <p className="text-[0.8rem] leading-relaxed text-text-secondary">
                Upload <code>.py</code>, <code>.html</code>, <code>.json</code>, <code>.txt</code> or{' '}
                <code>.mpy</code> files. <code>.html</code> lands in <code>www/</code>, everything else
                in the filesystem root. Settings, memory, the chat log, cron and the Telegram token are
                never overwritten by this endpoint.
              </p>

              <input
                type="file"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
                className="input cursor-pointer file:mr-3 file:border-0 file:bg-midground file:px-2 file:py-1 file:text-[0.7rem] file:font-bold file:uppercase file:tracking-[0.12em] file:text-background-base"
              />

              {files.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-[0.75rem] text-text-secondary">
                  {files.map((f) => (
                    <li key={f.name} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate font-mono-ui">{f.name}</span>
                      <span className="font-mono-ui text-[0.7rem] text-text-faint">{bytes(f.size)}</span>
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.72rem] text-text-faint">{progress}</span>
                <Button variant="primary" loading={busy} disabled={files.length === 0} onClick={() => void upload()}>
                  Upload &amp; reboot
                </Button>
              </div>
            </div>
          </Panel>

          <Panel title="Full UI redeploy" icon={<Download className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-2 px-3.5 py-3">
              <p className="text-[0.8rem] leading-relaxed text-text-secondary">
                The React dashboard is a compiled bundle (<code>www/index.html</code> plus{' '}
                <code>www/assets/</code>). Redeploy it over the serial port from the repo:
              </p>
              <pre className="overflow-x-auto border border-border bg-card px-2.5 py-2 font-mono-ui text-[0.72rem] leading-relaxed text-text-secondary">{`cd ui && npm run build
python -m mpremote connect COM11 fs mkdir :www/assets
python -m mpremote connect COM11 cp www/index.html :www/index.html
python -m mpremote connect COM11 cp www/assets/app.js :www/assets/app.js
python -m mpremote connect COM11 cp www/assets/app.css :www/assets/app.css
python -m mpremote connect COM11 reset`}</pre>
              <p className="text-[0.72rem] leading-relaxed text-text-faint">
                Firmware re-flashing (MicroPython itself) is a host-side <code>esptool</code> operation
                and cannot be done from the browser.
              </p>
            </div>
          </Panel>
        </div>
      </PageBody>
      {confirmNode}
    </>
  )
}
