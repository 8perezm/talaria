import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import {
  ArrowUp,
  ChevronDown,
  Cpu,
  Lock,
  Plus,
  Sparkles,
  Terminal,
  Wrench,
  Slash,
  CircleAlert,
} from 'lucide-react'
import { api, ApiError, getToken, type ChatLogEntry, type MemoryResponse } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAppData } from '@/lib/app-data'
import { Button, Chip, useToast } from '@/components/ui'
import { StatusChip } from '@/components/Shell'
import { Markdown } from '@/components/Markdown'

interface Turn {
  id: number
  role: 'user' | 'assistant'
  text: string
  reasoning?: string
  toolsUsed?: string
  streaming?: boolean
  error?: boolean
}

const SUGGESTIONS = [
  'What is my free heap right now?',
  'Turn on the LED on GPIO 2',
  'Read the temperature on ADC pin 4',
  'Write a haiku about microcontrollers',
  'Create a skill that reads the temperature sensor',
  'Create a cron job that reports free heap every hour',
]

let turnSeq = 0

export function ChatPage() {
  const { status, config, authed, refreshStatus } = useAppData()
  const { push } = useToast()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSession = searchParams.get('session') || ''

  const [turns, setTurns] = useState<Turn[]>([])
  const [sessionId, setSessionId] = useState('')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [modelOpen, setModelOpen] = useState(false)
  const [restored, setRestored] = useState(false)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  /* ---- restore transcript from the device session store ----
     `?session=<id>` opens (and activates) that conversation — this is how a
     row on the Sessions page resumes, and how a reload keeps its place.
     No param = whatever the device has active; the resolved id is then put
     in the URL so refreshing or sharing the link lands on the same session. */
  useEffect(() => {
    if (!authed || restored) return
    let cancelled = false
    void (async () => {
      try {
        // No explicit tail: the device returns the configured number of
        // turns (Config -> Chat history, default 20 = 40 log lines) using a
        // chunked read of the rolling log.
        const qs = urlSession
          ? `?session=${encodeURIComponent(urlSession)}&activate=1`
          : '?activate=1'
        const mem = await api.get<MemoryResponse>('/api/memory' + qs)
        if (cancelled) return
        const sid = typeof mem.session === 'string' ? mem.session : ''
        if (sid) {
          setSessionId(sid)
          if (!urlSession) setSearchParams({ session: sid }, { replace: true })
        }
        const tail = Array.isArray(mem.log_tail) ? mem.log_tail : []
        const restoredTurns: Turn[] = []
        for (const entry of tail) {
          if (!entry || typeof entry.content !== 'string' || !entry.content.trim()) continue
          const role = entry.role === 'user' ? 'user' : 'assistant'
          restoredTurns.push({ id: ++turnSeq, role, text: entry.content })
        }
        if (restoredTurns.length) setTurns(restoredTurns)
      } catch {
        /* empty log is fine */
      } finally {
        if (!cancelled) setRestored(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [authed, restored, urlSession, setSearchParams])

  /* A link/history change that swaps only the `?session=` value (same route)
     must reload the transcript; React Router does not remount for that. */
  useEffect(() => {
    if (!urlSession || urlSession === sessionId) return
    setTurns([])
    setRestored(false)
  }, [urlSession, sessionId])

  /* ---- model list: fetched lazily when the picker opens ----
     /api/models reaches out to the provider over TLS from the device and can
     take seconds. Loading it at page start would hold the request gate and
     delay the first paint, so it is fetched on demand instead. */
  const [modelsLoading, setModelsLoading] = useState(false)
  const loadModels = useCallback(async () => {
    if (models.length || modelsLoading) return
    setModelsLoading(true)
    try {
      const res = await api.get<{ models?: Array<{ id: string }> }>('/api/models')
      const ids = (res.models || []).map((m) => m.id).filter(Boolean)
      if (ids.length) setModels(ids)
    } catch {
      /* endpoint not configured yet */
    } finally {
      setModelsLoading(false)
    }
  }, [models.length, modelsLoading])

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [turns, scrollToBottom])

  const history = useMemo<ChatLogEntry[]>(
    () =>
      turns
        .filter((t) => !t.error && t.text.trim())
        .slice(-12)
        .map((t) => ({ role: t.role, content: t.text })),
    [turns],
  )

  const patchTurn = useCallback((id: number, patch: Partial<Turn>) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }, [])

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim()
      if (!message || busy) return
      if (!authed) {
        push('err', 'Unlock the dashboard first')
        return
      }
      setInput('')
      setBusy(true)

      const userTurn: Turn = { id: ++turnSeq, role: 'user', text: message }
      const replyTurn: Turn = { id: ++turnSeq, role: 'assistant', text: '', streaming: true }
      const replyId = replyTurn.id
      setTurns((prev) => [...prev, userTurn, replyTurn])

      const controller = new AbortController()
      abortRef.current = controller

      let acc = ''
      let reasoning = ''
      let needTools = false

      const finish = (patch: Partial<Turn>) => patchTurn(replyId, { streaming: false, ...patch })

      try {
        const res = await fetch('/api/chat-stream', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
          },
          body: JSON.stringify({ message, history, session: sessionId }),
          signal: controller.signal,
        })

        if (!res.ok) {
          const err = await res.text().catch(() => '')
          throw new ApiError(res.status, err || `HTTP ${res.status}`)
        }

        const reader = res.body?.getReader()
        if (!reader) throw new Error('stream unavailable')
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let idx: number
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 2)
            for (const line of frame.split('\n')) {
              if (!line.startsWith('data:')) continue
              const payload = line.slice(5).trim()
              if (!payload || payload === '[DONE]') continue
              let evt: Record<string, unknown>
              try {
                evt = JSON.parse(payload) as Record<string, unknown>
              } catch {
                continue
              }
              if (typeof evt.delta === 'string') {
                acc += evt.delta
                patchTurn(replyId, { text: acc })
              }
              if (typeof evt.reasoning === 'string') {
                reasoning = evt.reasoning
                patchTurn(replyId, { reasoning })
              }
              if (evt.need_tools) needTools = true
              if (typeof evt.error === 'string' && evt.error) {
                throw new Error(evt.error)
              }
            }
          }
        }

        if (needTools) {
          // Agentic turn: the tool loop lives behind the non-streaming
          // endpoint, exactly like upstream's need_tools fallback.
          patchTurn(replyId, { text: '', reasoning, streaming: true })
          const out = await api.post<{
            reply?: string
            tools_used?: string
            reasoning?: string
            error?: string
          }>('/api/chat', { message, history, session: sessionId })
          if (out.error) throw new Error(out.error)
          finish({
            text: out.reply || '',
            reasoning: out.reasoning || reasoning || undefined,
            toolsUsed: out.tools_used || undefined,
          })
        } else if (!acc.trim()) {
          finish({ text: '', error: true })
          patchTurn(replyId, {
            text: 'The model returned an empty reply. Check the model and endpoint in Config.',
            error: true,
          })
        } else {
          finish({ text: acc, reasoning: reasoning || undefined })
        }
        void refreshStatus()
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          finish({ text: acc, reasoning: reasoning || undefined })
        } else {
          const messageText = err instanceof Error ? err.message : String(err)
          finish({ text: messageText, error: true })
        }
      } finally {
        setBusy(false)
        abortRef.current = null
        inputRef.current?.focus()
      }
    },
    [authed, busy, history, patchTurn, push, refreshStatus, sessionId],
  )

  const stop = () => {
    abortRef.current?.abort()
  }

  /* New Chat = new conversation. The device creates the session id and
     points its active pointer at it; the file appears with the first turn. */
  const newChat = async () => {
    try {
      const res = await api.post<{ session?: string }>('/api/sessions', {})
      const sid = typeof res.session === 'string' ? res.session : ''
      abortRef.current?.abort()
      setTurns([])
      if (sid) {
        setSessionId(sid)
        setSearchParams({ session: sid }, { replace: true })
      }
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'New chat failed')
    }
  }

  const switchModel = async (model: string) => {
    setModelOpen(false)
    try {
      await api.post('/api/config', { model })
      push('ok', `Model set to ${model}`)
      void refreshStatus()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Model switch failed')
    }
  }

  /* ---- locked state ---- */
  if (!authed) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
        <Lock className="h-6 w-6 text-text-faint" />
        <p className="label-display text-[0.8rem] tracking-[0.16em] text-midground">
          Dashboard locked
        </p>
        <p className="max-w-sm text-[0.82rem] leading-relaxed text-text-tertiary">
          Sign in as admin with the device password to continue.
        </p>
        <Button onClick={() => navigate('/login')}>Go to Login</Button>
      </div>
    )
  }

  const empty = turns.length === 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ---- chat header ---- */}
      <div className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Terminal className="h-4 w-4 text-text-secondary" />
          <h1 className="label-display text-[0.9rem] font-bold tracking-[0.07em] text-midground">
            Chat
          </h1>
          <StatusChip />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {/* model picker */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setModelOpen((v) => !v)
                void loadModels()
              }}
              className="flex max-w-[16rem] items-center gap-1.5 border border-border px-2 py-1 text-[0.72rem] text-text-secondary hover:text-midground"
              aria-haspopup="listbox"
              aria-expanded={modelOpen}
            >
              <Cpu className="h-3 w-3 shrink-0" />
              <span className="truncate font-mono-ui">{status?.model || config?.model || 'no model'}</span>
              <ChevronDown className="h-3 w-3 shrink-0" />
            </button>
            {modelOpen && (
              <>
                <button
                  type="button"
                  aria-hidden
                  tabIndex={-1}
                  className="fixed inset-0 z-[60] cursor-default"
                  onClick={() => setModelOpen(false)}
                />
                <div
                  role="listbox"
                  className="absolute right-0 top-full z-[61] mt-1 max-h-72 w-[22rem] overflow-y-auto border border-border bg-background-base py-1 shadow-[0_18px_50px_rgba(0,0,0,0.55)]"
                >
                  <p className="px-3 py-1 label-display text-[0.6rem] tracking-[0.14em] text-text-faint">
                    Model
                  </p>
                  {modelsLoading && (
                    <p className="px-3 py-1.5 text-[0.72rem] text-text-faint">reading catalogue…</p>
                  )}
                  {(models.length ? models : [status?.model || config?.model || '']).filter(Boolean).map(
                    (m) => (
                      <button
                        key={m}
                        type="button"
                        role="option"
                        aria-selected={m === status?.model}
                        onClick={() => void switchModel(m)}
                        className={cn(
                          'block w-full truncate px-3 py-1.5 text-left font-mono-ui text-[0.74rem] hover:bg-midground/8',
                          m === status?.model ? 'text-midground' : 'text-text-secondary',
                        )}
                      >
                        {m}
                      </button>
                    ),
                  )}
                  {models.length === 0 && (
                    <p className="px-3 py-2 text-[0.72rem] text-text-faint">
                      No model list — configure the endpoint in{' '}
                      <button
                        type="button"
                        className="underline"
                        onClick={() => navigate('/config')}
                      >
                        Config
                      </button>
                      .
                    </p>
                  )}
                </div>
              </>
            )}
          </div>

          <Button
            variant="primary"
            size="sm"
            onClick={() => void newChat()}
            disabled={busy}
            title="Start a new conversation"
          >
            <Plus className="h-3 w-3" />
            New Chat
          </Button>
        </div>
      </div>

      {/* ---- transcript ---- */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {empty ? (
          <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center gap-4 px-4 py-10 text-center">
            <div className="flex items-center gap-2 text-midground">
              <Sparkles className="h-4 w-4" />
              <span className="label-display text-[0.78rem] tracking-[0.18em]">Talaria Agent</span>
            </div>
            <p className="max-w-md text-[0.86rem] leading-relaxed text-text-tertiary">
              A micro agent running on an ESP32-S3. Ask it something, or let it reach for the
              silicon — GPIO, ADC, files, the network.
            </p>
            <div className="grid w-full max-w-xl grid-cols-1 gap-1.5 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="border border-border px-3 py-2 text-left text-[0.78rem] text-text-secondary transition-colors hover:border-midground/40 hover:text-midground"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-1 py-4">
            {turns.map((turn) => (
              <TurnView key={turn.id} turn={turn} />
            ))}
            {busy && <div className="h-1" />}
          </div>
        )}
      </div>

      {/* ---- composer ---- */}
      <div className="shrink-0 pb-3">
        <div className="mx-auto max-w-3xl">
          <div
            className={cn(
              'border border-border bg-card transition-colors focus-within:border-midground/40',
            )}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send(input)
                }
              }}
              rows={2}
              placeholder={busy ? 'Waiting for the agent…' : 'Message the agent…'}
              className="w-full resize-none bg-transparent px-3 py-2.5 text-[0.88rem] leading-relaxed text-midground outline-none placeholder:text-text-faint"
              aria-label="Message"
            />
            <div className="flex items-center justify-between gap-2 border-t border-border/60 px-2 py-1.5">
              <div className="flex min-w-0 items-center gap-2 text-[0.66rem] text-text-faint">
                <span className="hidden items-center gap-1 sm:flex">
                  <kbd className="border border-border px-1 font-mono-ui">⏎</kbd> send
                </span>
                <span className="hidden items-center gap-1 sm:flex">
                  <kbd className="border border-border px-1 font-mono-ui">⇧⏎</kbd> newline
                </span>
                <Chip tone={status?.wifi_connected ? 'success' : 'warning'} dot>
                  {status?.wifi_connected ? 'wifi' : 'no wifi'}
                </Chip>
              </div>
              {busy ? (
                <Button variant="danger" size="sm" onClick={stop}>
                  <Slash className="h-3 w-3" />
                  Stop
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void send(input)}
                  disabled={!input.trim()}
                >
                  <ArrowUp className="h-3 w-3" />
                  Send
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function TurnView({ turn }: { turn: Turn }) {
  const [showReasoning, setShowReasoning] = useState(false)

  if (turn.role === 'user') {
    return (
      <div className="flex flex-col gap-1">
        <span className="label-display text-[0.6rem] tracking-[0.16em] text-text-faint">You</span>
        <div className="border-l border-midground/40 pl-3 text-[0.88rem] leading-relaxed text-midground whitespace-pre-wrap break-words">
          {turn.text}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="label-display text-[0.6rem] tracking-[0.16em] text-text-faint">Agent</span>
        {turn.toolsUsed && (
          <Chip tone="muted">
            <Wrench className="h-2.5 w-2.5" />
            {turn.toolsUsed}
          </Chip>
        )}
        {turn.streaming && <span className="text-[0.6rem] text-text-faint animate-pulse-soft">streaming</span>}
      </div>

      {turn.reasoning && (
        <div className="border border-border/70">
          <button
            type="button"
            onClick={() => setShowReasoning((v) => !v)}
            className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-[0.66rem] text-text-tertiary hover:text-midground"
          >
            <ChevronDown className={cn('h-3 w-3 transition-transform', !showReasoning && '-rotate-90')} />
            reasoning
          </button>
          {showReasoning && (
            <div className="whitespace-pre-wrap break-words border-t border-border/60 px-2 py-1.5 font-mono-ui text-[0.7rem] leading-relaxed text-text-tertiary">
              {turn.reasoning}
            </div>
          )}
        </div>
      )}

      {turn.error ? (
        <div className="flex items-start gap-2 border border-destructive/60 px-2.5 py-2 text-[0.8rem] text-destructive">
          <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="break-words">{turn.text || 'Request failed'}</span>
        </div>
      ) : (
        <div
          className={cn(
            'text-[0.88rem] leading-relaxed break-words',
            turn.streaming && !turn.text && 'text-text-faint',
          )}
        >
          {turn.text ? (
            <Markdown source={turn.text} className={turn.streaming ? 'caret' : undefined} />
          ) : (
            <span className="text-[0.8rem] text-text-faint">thinking…</span>
          )}
        </div>
      )}
    </div>
  )
}
