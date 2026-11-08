/**
 * Thin client for the MicroPython agent's REST API.
 *
 * Everything is same-origin (the ESP32 serves this bundle), so paths are
 * absolute and no base URL is needed. Auth is a bearer token kept in
 * localStorage under the same `esp32_token` key the legacy pages used, so
 * an already-unlocked browser stays unlocked after the upgrade.
 */

export const TOKEN_KEY = 'esp32_token'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Query = Record<string, string | number | boolean | undefined | null>

function withQuery(path: string, query?: Query) {
  if (!query) return path
  const parts: string[] = []
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  }
  return parts.length ? `${path}${path.includes('?') ? '&' : '?'}${parts.join('&')}` : path
}

async function toError(res: Response): Promise<ApiError> {
  let detail = ''
  try {
    const text = await res.text()
    if (text) {
      try {
        const parsed = JSON.parse(text) as { error?: string; detail?: string }
        detail = parsed.error || parsed.detail || text
      } catch {
        detail = text
      }
    }
  } catch {
    /* ignore */
  }
  if (res.status === 401) return new ApiError(401, 'Authentication required')
  return new ApiError(res.status, (detail || `HTTP ${res.status}`).slice(0, 240))
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  query?: Query
  signal?: AbortSignal
  raw?: boolean
}

/* ------------------------------------------------------------------ */
/* Concurrency gate                                                    */
/*                                                                     */
/* The ESP32 runs a single-threaded asyncio server over lwIP. When two  */
/* or three fresh connections arrive in the same instant, the extra     */
/* SYNs are dropped and TCP retransmits on a 1/2/4 s backoff — measured */
/* as a ~8 s stall on first paint while 300 ms requests sat queued.     */
/* Serialising to one in-flight request turns the whole startup fan-out */
/* into ~1.5 s of predictable round trips.                             */
/* ------------------------------------------------------------------ */
const MAX_CONCURRENT = 1
let active = 0
const waiters: Array<() => void> = []

function acquire(): Promise<void> {
  if (active < MAX_CONCURRENT) {
    active += 1
    return Promise.resolve()
  }
  return new Promise<void>((resolve) => {
    waiters.push(() => {
      active += 1
      resolve()
    })
  })
}

function release() {
  active -= 1
  const next = waiters.shift()
  if (next) next()
}

export async function request<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: string | undefined
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const url = withQuery(path, opts.query)
  const entry: { path: string; started: number; ended?: number; status?: number; error?: string } = {
    path: url,
    started: Date.now(),
  }
  noteStart(entry)
  await acquire()
  try {
    const res = await fetch(url, {
      method: opts.method || 'GET',
      headers,
      body,
      signal: opts.signal,
      cache: 'no-store',
    })
    entry.status = res.status
    if (!res.ok) throw await toError(res)
    if (opts.raw) return res as unknown as T
    const text = await res.text()
    entry.ended = Date.now()
    noteRequest(entry)
    if (!text) return {} as T
    try {
      return JSON.parse(text) as T
    } catch {
      return text as unknown as T
    }
  } catch (err) {
    entry.error = err instanceof Error ? err.message : String(err)
    entry.ended = Date.now()
    noteRequest(entry)
    throw err
  } finally {
    release()
  }
}
export const api = {
  get: <T = unknown>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T = unknown>(path: string, body?: unknown, query?: Query) =>
    request<T>(path, { method: 'POST', body, query }),
}

/* Field-visible request log (devtools: `__hermesNet`). Small and bounded —
   it is the fastest way to diagnose a stalled request on a device that has
   no console of its own. */
interface Trace {
  path: string
  started: number
  ended?: number
  status?: number
  error?: string
}
const trace: Trace[] = []
function noteStart(entry: Trace) {
  trace.push(entry)
  if (trace.length > 40) trace.shift()
  try {
    ;(window as unknown as Record<string, unknown>).__hermesNet = trace
  } catch {
    /* ignore */
  }
}

function noteRequest(entry: Trace) {
  if (trace.indexOf(entry) < 0) trace.push(entry)
  if (trace.length > 40) trace.shift()
  try {
    ;(window as unknown as Record<string, unknown>).__hermesNet = trace
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------------------------ */
/* Response shapes (loose on purpose — MicroPython emits optional keys) */
/* ------------------------------------------------------------------ */

export interface Status {
  auth_required?: boolean
  ap_mode?: boolean
  wifi_connected?: boolean
  ssid?: string
  ip?: string
  free_heap?: number
  uptime_s?: number
  fs_ok?: boolean
  tools_mask?: number
  model?: string
  log_bytes?: number
  mem_bytes?: number
  mdns?: string
  endpoint?: string
  endpoint_configured?: boolean
  firmware?: string
  version?: string
  boot_count?: number
}

export interface ConfigInfo {
  wifi_ssid?: string
  endpoint?: string
  model?: string
  api_key_masked?: string
  auth_required?: boolean
  gateway_configured?: boolean
  chat_entry_chars?: number
  chat_entry_chars_min?: number
  chat_entry_chars_max?: number
  chat_log_max_kb?: number
  chat_log_max_kb_min?: number
  chat_log_max_kb_max?: number
  chat_log_keep_kb?: number
  chat_log_keep_kb_min?: number
  chat_restore_turns?: number
  chat_restore_turns_min?: number
  chat_restore_turns_max?: number
}

export interface ChatLogEntry {
  role: 'user' | 'assistant' | 'system' | string
  content: string
}

export interface MemoryResponse {
  memory?: string
  fs_ok?: boolean
  log_bytes?: number
  log_tail?: ChatLogEntry[]
  clear_log?: boolean
}

export interface ToolInfo {
  name: string
  label?: string
  description?: string
  default_off?: boolean
  enabled?: boolean
  toolset?: string
}

export interface ToolsResponse {
  tools: ToolInfo[]
  mask?: number
  count?: number
}

export interface SkillInfo {
  name: string
  description?: string
  enabled?: boolean
  uses?: number
  source?: string
  triggers?: string[] | string
  body?: string
}

export interface SkillsResponse {
  skills: SkillInfo[]
  bundles?: unknown[]
  count?: number
}

export interface CronJob {
  id?: string | number
  name?: string
  schedule?: string
  when?: string
  prompt?: string
  message?: string
  enabled?: boolean
  last_run?: number | string | null
  next_run?: number | string | null
  runs?: number
  delivery?: string
}

export interface CronResponse {
  jobs: CronJob[]
  count?: number
  max_jobs?: number
  success?: boolean
}

export interface GatewayRequest {
  id?: string | number
  platform?: string
  from?: string
  text?: string
  ts?: number
  status?: string
}

export interface GatewayResponse {
  configured?: boolean
  allow?: string[]
  requests?: GatewayRequest[]
  offset?: number
  success?: boolean
  platforms?: Array<{ name: string; enabled?: boolean; configured?: boolean }>
}

export interface LogEntry {
  seq: number
  msg: string
}

export interface LogsResponse {
  entries: LogEntry[]
  seq?: number
  count?: number
}

export interface FileEntry {
  name: string
  type: 'file' | 'dir' | string
  size?: number
  modified?: number
}

export interface FilesResponse {
  path?: string
  entries: FileEntry[]
  error?: string
}

export interface StatsResponse {
  [key: string]: unknown
}
