import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { api, ApiError, getToken, setToken, type ConfigInfo, type Status } from '@/lib/api'

interface AppData {
  status: Status | null
  config: ConfigInfo | null
  statusError: string | null
  authed: boolean
  refreshStatus: () => Promise<void>
  refreshConfig: () => Promise<void>
  unlock: (token: string) => Promise<boolean>
  lock: () => void
  online: boolean
}

const AppDataContext = createContext<AppData | null>(null)

export function useAppData() {
  const ctx = useContext(AppDataContext)
  if (!ctx) throw new Error('useAppData outside provider')
  return ctx
}

const STATUS_POLL_MS = 5000

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [config, setConfig] = useState<ConfigInfo | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [authed, setAuthed] = useState(true)
  const [online, setOnline] = useState(true)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.get<Status>('/api/status')
      if (!mounted.current) return
      setStatus(next)
      setStatusError(null)
      setOnline(true)
      if (next.auth_required === false) setAuthed(true)
    } catch (err) {
      if (!mounted.current) return
      if (err instanceof ApiError && err.status === 401) {
        setAuthed(false)
        setStatusError(null)
        setOnline(true)
        return
      }
      setOnline(false)
      setStatusError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  const refreshConfig = useCallback(async () => {
    try {
      const next = await api.get<ConfigInfo>('/api/config')
      if (mounted.current) setConfig(next)
    } catch {
      /* auth-gated; status handles it */
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
    void refreshConfig()
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshStatus()
    }, STATUS_POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refreshStatus()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refreshStatus, refreshConfig])

  const unlock = useCallback(
    async (token: string) => {
      setToken(token.trim())
      try {
        const next = await api.get<Status>('/api/status')
        setStatus(next)
        setAuthed(true)
        setStatusError(null)
        void refreshConfig()
        return true
      } catch {
        setToken('')
        setAuthed(false)
        return false
      }
    },
    [refreshConfig],
  )

  const lock = useCallback(() => {
    setToken('')
    setAuthed(false)
  }, [])

  const value = useMemo<AppData>(
    () => ({
      status,
      config,
      statusError,
      authed,
      refreshStatus,
      refreshConfig,
      unlock,
      lock,
      online,
    }),
    [status, config, statusError, authed, refreshStatus, refreshConfig, unlock, lock, online],
  )

  // Debug hook: lets a support session inspect live provider state from the
  // devtools console without a REPL on the device.
  if (typeof window !== 'undefined') {
    ;(window as unknown as Record<string, unknown>).__hermes = value
  }

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>
}

/** Polled GET helper for pages: returns data, error, and a manual reload. */
export function usePolled<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  intervalMs = 0,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await loaderRef.current(signal ?? new AbortController().signal)
      setData(next)
      setError(null)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    void load(controller.signal)
    let id: ReturnType<typeof setInterval> | undefined
    if (intervalMs > 0) {
      id = setInterval(() => {
        if (document.visibilityState === 'visible') void load(controller.signal)
      }, intervalMs)
    }
    return () => {
      controller.abort()
      if (id) clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, load, ...deps])

  return { data, error, loading, reload: () => load(), setData }
}

export function useAuthToken() {
  return getToken()
}
