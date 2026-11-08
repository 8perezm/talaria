import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Eye, EyeOff, KeyRound } from 'lucide-react'
import { useAppData } from '@/lib/app-data'

/**
 * Full-screen Hermes-style sign-in.
 *
 * Fixed username `admin`; the password is the device auth token
 * (security.auth_token in config.yaml). Verification happens against
 * POST /api/login on new firmware with a Bearer-status fallback, inside
 * `unlock()` — this page is presentation only. Talaria palette, square
 * corners, no external assets.
 */
export function LoginPage() {
  const { status, authed, unlock } = useAppData()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Already unlocked (or open device) — no reason to sit on the gate.
  useEffect(() => {
    if (authed && status?.auth_required === false) navigate('/', { replace: true })
    else if (authed) navigate('/', { replace: true })
  }, [authed, status?.auth_required, navigate])

  const submit = async () => {
    if (busy) return
    if (!username.trim() || !password) {
      setError('Enter the username and password.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const ok = await unlock(username, password)
      if (ok) {
        setPassword('')
        navigate('/', { replace: true })
      } else {
        setError('Invalid username or password.')
      }
    } catch {
      setError('Sign-in failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background-base px-4 py-10">
      <main className="w-full max-w-sm">
        <p className="label-display mb-4 text-center text-[0.95rem] tracking-[0.3em] text-midground">
          Talaria Agent
        </p>
        <div className="border border-border bg-background-base px-6 pb-6 pt-5">
          <h1 className="label-display text-[1.1rem] font-bold tracking-[0.08em] text-midground">
            Sign in
          </h1>
          <p className="mt-1 text-[0.8rem] leading-relaxed text-text-secondary">
            Sign in with your device username and password to continue to the
            dashboard.
          </p>
          <form
            className="mt-4 flex flex-col gap-3"
            autoComplete="on"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="field-label">Username</span>
              <input
                className="input font-mono-ui"
                type="text"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="field-label">Password</span>
              <div className="flex gap-1.5">
                <input
                  className="input font-mono-ui"
                  type={show ? 'text' : 'password'}
                  name="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="device password"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                  className="btn btn-sm shrink-0"
                >
                  {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </button>
              </div>
            </label>
            {error && (
              <p role="alert" className="text-[0.78rem] text-destructive">
                {error}
              </p>
            )}
            <button type="submit" disabled={busy || !username.trim() || !password} className="btn btn-primary mt-1 w-full">
              <KeyRound className="h-3 w-3" />
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
        <p className="mt-4 text-center text-[0.68rem] uppercase tracking-[0.14em] text-text-faint">
          {status?.auth_required === false ? 'Open device · auth not required' : 'Auth required'}
        </p>
      </main>
    </div>
  )
}
