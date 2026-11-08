import { useEffect, useState } from 'react'
import { Eye, EyeOff, KeyRound, Lock, Shield, Unlock } from 'lucide-react'
import { api, getToken, setToken } from '@/lib/api'
import { useAppData } from '@/lib/app-data'
import { Button, Chip, Field, Panel, StatStrip, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface AuthState {
  auth_required?: boolean
  ap_mode?: boolean
}

export function KeysPage() {
  const { status, authed, unlock, lock, refreshStatus } = useAppData()
  const { push } = useToast()

  const [required, setRequired] = useState<boolean>(!!status?.auth_required)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [unlockUser, setUnlockUser] = useState('admin')
  const [unlockToken, setUnlockToken] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        const res = await api.get<AuthState>('/api/auth')
        setRequired(!!res.auth_required)
      } catch {
        setRequired(!!status?.auth_required)
      }
    })()
  }, [status?.auth_required])

  const storedToken = getToken()

  const saveToken = async (value: string, label: string) => {
    setBusy(label)
    try {
      const res = await api.post<{ ok?: boolean; error?: string; auth_required?: boolean }>(
        '/api/auth',
        { token: value },
      )
      if (res.error) throw new Error(res.error)
      setToken(value)
      setRequired(!!res.auth_required)
      setNext('')
      setConfirm('')
      setCurrent('')
      push('ok', value ? 'Auth token updated' : 'Auth token cleared')
      await refreshStatus()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Update failed')
    } finally {
      setBusy(null)
    }
  }

  const doUnlock = async () => {
    const ok = await unlock(unlockUser, unlockToken)
    if (ok) {
      push('ok', 'Dashboard unlocked')
      setUnlockToken('')
    } else {
      push('err', 'Invalid username or password')
    }
  }

  const tokenMatches = next.length >= 8 && next === confirm

  return (
    <>
      <PageHeader
        title="Keys"
        icon={<KeyRound className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          authed ? (
            <Button size="sm" variant="ghost" onClick={lock}>
              <Lock className="h-3 w-3" /> Lock now
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="flex max-w-3xl flex-col gap-3">
          <StatStrip
            items={[
              {
                label: 'Auth',
                value: required ? 'required' : 'open',
                tone: required ? 'success' : 'warning',
              },
              { label: 'Session', value: authed ? 'unlocked' : 'locked', tone: authed ? 'success' : 'danger' },
              { label: 'Token', value: storedToken ? 'stored' : 'none', tone: storedToken ? 'success' : 'warning' },
              { label: 'Transport', value: 'bearer' },
            ]}
          />

          {!authed && (
            <Panel title="Unlock this dashboard" icon={<Unlock className="h-3.5 w-3.5" />}>
              <div className="flex flex-col gap-3 px-3.5 py-3">
                <p className="text-[0.8rem] leading-relaxed text-text-secondary">
                  Sign in as <code>admin</code> with the device password — or use the full{' '}
                  <a href="/login" className="underline underline-offset-2">
                    login screen
                  </a>
                  . The password is stored in this browser's localStorage only, and sent as a
                  bearer header.
                </p>
                <div className="flex flex-col gap-1.5 sm:flex-row">
                  <input
                    className="input font-mono-ui sm:max-w-40"
                    type="text"
                    value={unlockUser}
                    onChange={(e) => setUnlockUser(e.target.value)}
                    placeholder="admin"
                    autoComplete="username"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    aria-label="Username"
                  />
                  <input
                    className="input font-mono-ui"
                    type={show ? 'text' : 'password'}
                    value={unlockToken}
                    onChange={(e) => setUnlockToken(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void doUnlock()
                    }}
                    placeholder="device password"
                    autoComplete="current-password"
                    aria-label="Password"
                  />
                  <Button variant="ghost" size="sm" onClick={() => setShow((v) => !v)}>
                    {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                  </Button>
                  <Button variant="primary" size="sm" onClick={() => void doUnlock()} disabled={!unlockUser.trim() || !unlockToken}>
                    Unlock
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          <Panel title="Provider API key" icon={<KeyRound className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-2 px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.78rem] text-text-secondary">Stored upstream credential</span>
                {authed ? (
                  <Chip tone={status?.endpoint_configured ? 'success' : 'danger'}>
                    {status?.endpoint_configured ? 'configured' : 'missing'}
                  </Chip>
                ) : (
                  <Chip tone="muted">unknown while locked</Chip>
                )}
              </div>
              <p className="text-[0.72rem] leading-relaxed text-text-faint">
                The provider key lives in <code>config.yaml</code> and is never returned in full —
                only a masked form. Change it on the Config page.
              </p>
              <div>
                <a href="/config" className="btn btn-sm">
                  Open Config
                </a>
              </div>
            </div>
          </Panel>

          <Panel title="Device auth token" icon={<Shield className="h-3.5 w-3.5" />}>
            <div className="flex flex-col gap-3 px-3.5 py-3">
              <div className="flex items-center gap-2">
                <Chip tone={required ? 'success' : 'warning'} dot>
                  {required ? 'enforced' : 'not enforced'}
                </Chip>
                <span className="text-[0.72rem] text-text-faint">
                  Minimum 8 characters. Clearing it leaves the device open on the LAN.
                </span>
              </div>

              <Field label="Current token" hint="Required to change or clear the token.">
                <input
                  className="input font-mono-ui"
                  type={show ? 'text' : 'password'}
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  autoComplete="off"
                />
              </Field>

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="New token">
                  <input
                    className="input font-mono-ui"
                    type={show ? 'text' : 'password'}
                    value={next}
                    onChange={(e) => setNext(e.target.value)}
                    autoComplete="off"
                  />
                </Field>
                <Field label="Confirm">
                  <input
                    className="input font-mono-ui"
                    type={show ? 'text' : 'password'}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    autoComplete="off"
                  />
                </Field>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                <Button variant="ghost" size="sm" onClick={() => setShow((v) => !v)}>
                  {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                  {show ? 'Hide' : 'Show'}
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={!tokenMatches}
                  loading={busy === 'set'}
                  onClick={() => void saveToken(next, 'set')}
                >
                  Set token
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={!current.trim()}
                  loading={busy === 'clear'}
                  onClick={() => void saveToken('', 'clear')}
                >
                  Clear token
                </Button>
                {next && !tokenMatches && (
                  <span className="text-[0.72rem] text-warning">
                    {next.length < 8 ? 'too short' : 'does not match'}
                  </span>
                )}
              </div>
            </div>
          </Panel>
        </div>
      </PageBody>
    </>
  )
}
