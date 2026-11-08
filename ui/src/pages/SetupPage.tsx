import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowRight, Cpu, Link2, Sparkles, Wifi } from 'lucide-react'
import { api } from '@/lib/api'
import { useAppData } from '@/lib/app-data'
import { Button, Chip, Field, Panel, StatStrip, useToast } from '@/components/ui'
import { PageBody, PageHeader } from '@/components/Shell'

interface ScanResult {
  networks?: Array<{ ssid: string; rssi?: number; auth?: number }>
  error?: string
}

export function SetupPage() {
  const { status, config, refreshStatus, refreshConfig } = useAppData()
  const { push } = useToast()
  const navigate = useNavigate()

  const [endpoint, setEndpoint] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [ssid, setSsid] = useState('')
  const [password, setPassword] = useState('')
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [scanning, setScanning] = useState(false)

  useEffect(() => {
    if (config?.endpoint) setEndpoint((v) => v || config.endpoint || '')
    if (config?.model) setModel((v) => v || config.model || '')
    if (config?.wifi_ssid) setSsid((v) => v || config.wifi_ssid || '')
  }, [config])

  const ready = Boolean(config?.endpoint && config?.api_key_masked)
  const online = Boolean(status?.wifi_connected)

  const saveAgent = async () => {
    setBusy('agent')
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/agent', {
        endpoint: endpoint.trim(),
        model: model.trim(),
        ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
      })
      if (res.error) throw new Error(res.error)
      push('ok', 'Provider saved')
      setApiKey('')
      await refreshStatus()
      await refreshConfig()
      setStep(2)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(null)
    }
  }

  const doScan = async () => {
    setScanning(true)
    try {
      const res = await api.get<ScanResult>('/api/scan')
      setScan(res)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const saveWifi = async () => {
    setBusy('wifi')
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/wifi', {
        ssid: ssid.trim(),
        password,
      })
      if (res.error) throw new Error(res.error)
      push('info', 'WiFi saved — rebooting into your network')
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'WiFi save failed')
    } finally {
      setBusy(null)
    }
  }

  const STEPS = ['Network', 'Provider', 'Ready']

  return (
    <>
      <PageHeader
        title="Setup"
        icon={<Sparkles className="h-4 w-4" />}
        actions={<Chip tone={ready && online ? 'success' : 'warning'} dot>{ready && online ? 'ready' : 'setup needed'}</Chip>}
      />
      <PageBody>
        <div className="flex max-w-3xl flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Step', value: `${step + 1}/${STEPS.length}` },
              { label: 'WiFi', value: online ? 'connected' : 'off', tone: online ? 'success' : 'warning' },
              { label: 'Provider', value: ready ? 'configured' : 'missing', tone: ready ? 'success' : 'warning' },
              { label: 'Model', value: config?.model ? 'set' : 'unset', tone: config?.model ? 'success' : 'warning' },
            ]}
          />

          <div className="flex items-stretch border border-border">
            {STEPS.map((label, index) => (
              <button
                key={label}
                type="button"
                onClick={() => setStep(index)}
                className={
                  'flex flex-1 items-center justify-center gap-1.5 border-r border-border px-2 py-1.5 label-display text-[0.68rem] last:border-r-0 ' +
                  (index === step
                    ? 'bg-midground text-background-base'
                    : 'text-text-secondary hover:bg-midground/8')
                }
              >
                <span className="tabular-nums opacity-70">{index + 1}</span>
                {label}
              </button>
            ))}
          </div>

          {step === 0 && (
            <Panel title="WiFi network" icon={<Wifi className="h-3.5 w-3.5" />}>
              <div className="flex flex-col gap-3 px-3.5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={online ? 'success' : 'warning'} dot>
                    {online ? `on ${status?.ssid || 'network'}` : 'not connected'}
                  </Chip>
                  <Chip tone="muted">{status?.ip || 'no ip'}</Chip>
                  <Button size="sm" variant="ghost" loading={scanning} onClick={() => void doScan()}>
                    Scan
                  </Button>
                </div>

                {scan?.networks && scan.networks.length > 0 && (
                  <div className="max-h-44 overflow-y-auto border border-border">
                    <ul className="divide-y divide-border/50">
                      {scan.networks
                        .filter((n) => n.ssid)
                        .sort((a, b) => (b.rssi || -999) - (a.rssi || -999))
                        .map((n) => (
                          <li key={n.ssid}>
                            <button
                              type="button"
                              onClick={() => setSsid(n.ssid)}
                              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.78rem] hover:bg-midground/5"
                            >
                              <span className="min-w-0 flex-1 truncate">{n.ssid}</span>
                              <span className="font-mono-ui text-[0.7rem] tabular-nums text-text-faint">
                                {n.rssi} dBm
                              </span>
                            </button>
                          </li>
                        ))}
                    </ul>
                  </div>
                )}

                <Field label="SSID">
                  <input
                    className="input"
                    value={ssid}
                    onChange={(e) => setSsid(e.target.value)}
                    placeholder="your-network"
                  />
                </Field>
                <Field label="Password" hint="Saving reboots the device — the page will reconnect on the new network.">
                  <input
                    className="input"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    autoComplete="off"
                  />
                </Field>

                <div className="flex justify-between gap-2">
                  <Button variant="ghost" onClick={() => setStep(1)}>
                    Skip
                  </Button>
                  <Button
                    variant="primary"
                    disabled={!ssid.trim()}
                    loading={busy === 'wifi'}
                    onClick={() => void saveWifi()}
                  >
                    Save &amp; reboot
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          {step === 1 && (
            <Panel title="Model provider" icon={<Link2 className="h-3.5 w-3.5" />}>
              <div className="flex flex-col gap-3 px-3.5 py-3">
                <Field label="Endpoint" hint="Any OpenAI-compatible base URL.">
                  <input
                    className="input font-mono-ui text-[0.78rem]"
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                    placeholder="https://api.deepinfra.com/v1/openai"
                  />
                </Field>
                <Field label="Model">
                  <input
                    className="input font-mono-ui text-[0.78rem]"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="deepseek-ai/DeepSeek-V4.1-Flash"
                  />
                </Field>
                <Field
                  label="API key"
                  hint={config?.api_key_masked ? `Currently stored: ${config.api_key_masked}` : 'Paste the provider key.'}
                >
                  <input
                    className="input font-mono-ui text-[0.78rem]"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-…"
                    autoComplete="off"
                  />
                </Field>
                <div className="flex justify-between gap-2">
                  <Button variant="ghost" onClick={() => setStep(0)}>
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    disabled={!endpoint.trim()}
                    loading={busy === 'agent'}
                    onClick={() => void saveAgent()}
                  >
                    Save provider
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          {step === 2 && (
            <Panel title="You're ready" icon={<Cpu className="h-3.5 w-3.5" />}>
              <div className="flex flex-col gap-3 px-3.5 py-3">
                <ul className="flex flex-col gap-1.5 text-[0.82rem]">
                  {[
                    ['WiFi', online, status?.ssid || 'not connected'],
                    ['Provider endpoint', Boolean(config?.endpoint), config?.endpoint || 'unset'],
                    ['API key', Boolean(config?.api_key_masked), config?.api_key_masked || 'unset'],
                    ['Model', Boolean(config?.model), config?.model || 'unset'],
                  ].map(([label, ok, detail]) => (
                    <li key={String(label)} className="flex items-center gap-2">
                      <span className={ok ? 'dot text-success' : 'dot text-destructive'} />
                      <span className="w-36 shrink-0 text-text-faint">{String(label)}</span>
                      <span className="min-w-0 flex-1 truncate font-mono-ui text-text-secondary">
                        {String(detail)}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-1.5">
                  <Button variant="primary" onClick={() => navigate('/')}>
                    Open Chat <ArrowRight className="h-3 w-3" />
                  </Button>
                  <Button variant="ghost" onClick={() => navigate('/system')}>
                    Run diagnostics
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          <p className="px-1 text-[0.72rem] leading-relaxed text-text-faint">
            The device also exposes a captive portal when it cannot join a network: connect to
            <code> ESP32-Agent-Setup</code> and you will land on the WiFi page automatically.
          </p>
        </div>
      </PageBody>
    </>
  )
}
