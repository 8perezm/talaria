import { useState } from 'react'
import { Ban, Check, MessageCircle, Radio, RefreshCw, Send, Trash2, UserPlus } from 'lucide-react'
import { api } from '@/lib/api'
import { usePolled } from '@/lib/app-data'
import { Button, Chip, EmptyState, ErrorNote, Field, Loading, Modal, Panel, StatStrip, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface GatewayState {
  success?: boolean
  configured?: boolean
  allow?: Array<string | number>
  requests?: Array<{ id?: string | number; name?: string; username?: string; text?: string; ts?: number }>
  offset?: number
  error?: string
  note?: string
}

const CHANNELS = [
  {
    id: 'telegram',
    label: 'Telegram',
    detail: 'Long-poll gateway — chat with the agent from your phone.',
    credential: 'tg.json',
  },
]

export function ChannelsPage() {
  const { push } = useToast()
  const [allowOpen, setAllowOpen] = useState(false)
  const [allowId, setAllowId] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const gateway = usePolled<GatewayState>((signal) => api.get('/api/gateway', undefined, signal), 8000)

  const state = gateway.data
  const allow = state?.allow || []
  const requests = state?.requests || []

  const op = async (body: Record<string, unknown>, label: string) => {
    setBusy(label)
    try {
      const res = await api.post<GatewayState>('/api/gateway', body)
      if (!res.success) throw new Error(res.error || `${label} failed`)
      push('ok', `${label} ok`)
      gateway.reload()
      return true
    } catch (err) {
      push('err', err instanceof Error ? err.message : `${label} failed`)
      return false
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Channels"
        icon={<Radio className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => gateway.reload()}>
              <RefreshCw className="h-3 w-3" /> Refresh
            </Button>
            <Button size="sm" onClick={() => setAllowOpen(true)}>
              <UserPlus className="h-3 w-3" /> Allow chat
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              {
                label: 'Gateway',
                value: state?.configured ? 'configured' : 'not configured',
                tone: state?.configured ? 'success' : 'warning',
              },
              { label: 'Allowed chats', value: allow.length },
              {
                label: 'Pairing requests',
                value: requests.length,
                tone: requests.length ? 'warning' : 'default',
              },
              { label: 'Offset', value: state?.offset ?? 0 },
            ]}
          />

          {gateway.error && <ErrorNote onRetry={gateway.reload}>{gateway.error}</ErrorNote>}

          {CHANNELS.map((channel) => (
            <Panel
              key={channel.id}
              title={channel.label}
              icon={<MessageCircle className="h-3.5 w-3.5" />}
              actions={
                <Chip tone={state?.configured ? 'success' : 'muted'} dot>
                  {state?.configured ? 'credentials present' : 'no credentials'}
                </Chip>
              }
            >
              <div className="flex flex-col gap-2 px-3.5 py-3">
                <p className="text-[0.78rem] leading-relaxed text-text-secondary">{channel.detail}</p>
                <p className="text-[0.72rem] leading-relaxed text-text-faint">
                  The bot token is file-only: it lives in <code>{channel.credential}</code> on the
                  device and is never accepted over the API. Any <code>bot_token</code> sent to this
                  endpoint is ignored by design.
                </p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip tone={allow.length ? 'success' : 'warning'}>
                    {allow.length ? `${allow.length} allowed` : 'allowlist empty'}
                  </Chip>
                  <Chip tone={requests.length ? 'warning' : 'muted'}>
                    {requests.length ? `${requests.length} pending` : 'no requests'}
                  </Chip>
                </div>
              </div>
            </Panel>
          ))}

          <Panel
            title="Pairing requests"
            icon={<Send className="h-3.5 w-3.5" />}
            actions={
              requests.length > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    void op({ op: 'allow', ids: requests.map((r) => r.id).filter(Boolean) }, 'Allow all')
                  }
                >
                  Allow all
                </Button>
              ) : undefined
            }
          >
            {gateway.loading && !state ? (
              <Loading label="Reading gateway state…" />
            ) : requests.length === 0 ? (
              <EmptyState
                icon={<MessageCircle className="h-5 w-5" />}
                title="No pending requests"
                detail="When someone messages the bot, their chat appears here until you allow it."
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {requests.map((req) => (
                  <li key={String(req.id)} className="flex flex-wrap items-center gap-2 px-3.5 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="font-mono-ui text-[0.8rem] text-midground">
                        {req.name || req.username || 'unknown'} · {req.id}
                      </p>
                      {req.text && (
                        <p className="mt-0.5 line-clamp-1 text-[0.74rem] text-text-faint">{req.text}</p>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => void op({ op: 'allow', id: req.id }, 'Allow')}>
                        <Check className="h-3 w-3" /> Allow
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => void op({ op: 'deny', id: req.id }, 'Deny')}
                      >
                        <Ban className="h-3 w-3" /> Deny
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Allowlist" icon={<Check className="h-3.5 w-3.5" />}>
            {allow.length === 0 ? (
              <EmptyState
                icon={<Ban className="h-5 w-5" />}
                title="Nobody allowed yet"
                detail="Only allowlisted chats may talk to the agent. Add a chat id manually or approve a pending request."
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {allow.map((id) => (
                  <li key={String(id)} className="flex items-center gap-2 px-3.5 py-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                    <span className="min-w-0 flex-1 truncate font-mono-ui text-[0.78rem] text-text-secondary">
                      {String(id)}
                    </span>
                    <button
                      type="button"
                      title="Remove"
                      aria-label={`Remove ${id}`}
                      onClick={() => void op({ op: 'deny', id }, 'Remove')}
                      className="p-1 text-text-tertiary hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </PageBody>

      <Modal
        open={allowOpen}
        title="Allow a chat"
        onClose={() => setAllowOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAllowOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!allowId.trim()}
              loading={busy === 'Allow'}
              onClick={async () => {
                const ok = await op({ op: 'allow', id: allowId.trim() }, 'Allow')
                if (ok) {
                  setAllowId('')
                  setAllowOpen(false)
                }
              }}
            >
              Allow
            </Button>
          </>
        }
      >
        <Field label="Chat id" hint="The numeric Telegram chat id shown in a pairing request.">
          <input
            className="input font-mono-ui"
            autoFocus
            value={allowId}
            onChange={(e) => setAllowId(e.target.value)}
            placeholder="123456789"
          />
        </Field>
      </Modal>
    </>
  )
}
