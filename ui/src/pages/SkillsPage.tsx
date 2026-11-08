import { useMemo, useState } from 'react'
import { BookMarked, Eye, Loader2, Plus, Search, Sparkles, Trash2, Zap } from 'lucide-react'
import { api } from '@/lib/api'
import { usePolled } from '@/lib/app-data'
import { cn } from '@/lib/utils'
import { Button, EmptyState, ErrorNote, Field, Loading, Modal, Panel, StatStrip, useConfirm, useToast } from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

interface SkillEntry {
  name: string
  desc?: string
  description?: string
}

interface SkillsResponse {
  skills?: SkillEntry[]
  bundles?: unknown[]
  count?: number
  error?: string
}

interface SkillView {
  success?: boolean
  name?: string
  desc?: string
  content?: string
  size?: number
  warnings?: string[]
  error?: string
}

interface PendingItem {
  id?: number
  name?: string
  op?: string
  content?: string
  reason?: string
  ts?: number
}

const TEMPLATE = `---
description: One line describing when to use this skill.
---

# Skill name

## When to use
Describe the trigger.

## Steps
1. First step
2. Second step

## Notes
- Anything the agent should remember.
`

export function SkillsPage() {
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const [query, setQuery] = useState('')
  const [viewing, setViewing] = useState<SkillView | null>(null)
  const [viewBusy, setViewBusy] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newContent, setNewContent] = useState(TEMPLATE)
  const [saving, setSaving] = useState(false)
  const [showPending, setShowPending] = useState(false)

  const skills = usePolled<SkillsResponse>(
    (signal) => api.get('/api/skills', { pending: 1 }, signal),
    0,
  )

  const pending = (skills.data as SkillsResponse & { pending?: PendingItem[] })?.pending || []
  const list = skills.data?.skills || []

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) || (s.desc || s.description || '').toLowerCase().includes(q),
    )
  }, [list, query])

  const openSkill = async (name: string) => {
    setViewBusy(name)
    try {
      const res = await api.get<SkillView>('/api/skills', { name })
      if (res.error) throw new Error(res.error)
      setViewing(res)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Read failed')
    } finally {
      setViewBusy(null)
    }
  }

  const create = async () => {
    if (!newName.trim() || !newContent.trim()) return
    setSaving(true)
    try {
      const res = await api.post<{ success?: boolean; ok?: boolean; error?: string }>('/api/skills', {
        action: 'create',
        name: newName.trim(),
        content: newContent,
      })
      if (!res.success && !res.ok) throw new Error(res.error || 'create failed')
      push('ok', `Skill ${newName.trim()} created`)
      setCreateOpen(false)
      setNewName('')
      setNewContent(TEMPLATE)
      skills.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (name: string) => {
    const ok = await confirm('Delete skill', `"${name}" is removed from the device filesystem. This cannot be undone.`)
    if (!ok) return
    try {
      const res = await api.post<{ success?: boolean; ok?: boolean; error?: string }>('/api/skills', {
        action: 'delete',
        name,
      })
      if (!res.success && !res.ok) throw new Error(res.error || 'delete failed')
      push('ok', `Deleted ${name}`)
      skills.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const decidePending = async (action: 'approve' | 'reject', id?: number) => {
    try {
      const res = await api.post<{ success?: boolean; ok?: boolean; error?: string }>('/api/skills', {
        action,
        ids: id ?? 'all',
      })
      if (!res.success && !res.ok) throw new Error(res.error || `${action} failed`)
      push('ok', `${action === 'approve' ? 'Approved' : 'Rejected'} ${id ?? 'all pending'}`)
      skills.reload()
    } catch (err) {
      push('err', err instanceof Error ? err.message : `${action} failed`)
    }
  }

  return (
    <>
      <PageHeader
        title="Skills"
        icon={<Zap className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => setShowPending((v) => !v)}>
              <BookMarked className="h-3 w-3" /> Pending {pending.length ? `(${pending.length})` : ''}
            </Button>
            <Button size="sm" variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3 w-3" /> New skill
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <StatStrip
            items={[
              { label: 'Skills', value: list.length },
              { label: 'Pending', value: pending.length, tone: pending.length ? 'warning' : 'default' },
              { label: 'In view', value: filtered.length },
              { label: 'Max size', value: '3 KB' },
            ]}
          />

          {showPending && (
            <Panel
              title="Write approvals"
              icon={<BookMarked className="h-3.5 w-3.5" />}
              actions={
                pending.length > 0 ? (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => void decidePending('approve')}>
                      Approve all
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => void decidePending('reject')}>
                      Reject all
                    </Button>
                  </>
                ) : undefined
              }
            >
              {pending.length === 0 ? (
                <EmptyState
                  icon={<BookMarked className="h-5 w-5" />}
                  title="Nothing staged"
                  detail="When write-approval is enabled, agent-authored skills land here for your review before they go live."
                />
              ) : (
                <ul className="divide-y divide-border/60">
                  {pending.map((item, index) => (
                    <li key={item.id ?? index} className="flex flex-wrap items-start gap-2 px-3.5 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="font-mono-ui text-[0.8rem] text-midground">
                          {item.name || '(unnamed)'}
                          {item.op && <span className="ml-2 text-[0.68rem] text-text-faint">{item.op}</span>}
                        </p>
                        {item.reason && (
                          <p className="mt-0.5 line-clamp-2 text-[0.74rem] text-text-faint">{item.reason}</p>
                        )}
                      </div>
                      <div className="flex gap-1">
                        <Button size="sm" onClick={() => void decidePending('approve', item.id)}>
                          Approve
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => void decidePending('reject', item.id)}>
                          Reject
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          )}

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
            <input
              className="input pl-8"
              placeholder="Filter skills…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {skills.error && <ErrorNote onRetry={skills.reload}>{skills.error}</ErrorNote>}

          <Panel title="Installed skills" icon={<Sparkles className="h-3.5 w-3.5" />}>
            {skills.loading && !skills.data ? (
              <Loading label="Reading skills directory…" />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<Zap className="h-5 w-5" />}
                title={query ? 'No skills match' : 'No skills installed'}
                detail={
                  query
                    ? 'Clear the filter to see everything.'
                    : 'Skills are procedural memory: short markdown playbooks the agent loads on demand. Create one here, or let the agent draft them with /learn.'
                }
                action={<Button onClick={() => setCreateOpen(true)}>Create a skill</Button>}
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {filtered.map((skill) => (
                  <li key={skill.name} className="flex items-start gap-3 px-3.5 py-2.5 hover:bg-midground/3">
                    <div className="min-w-0 flex-1">
                      <p className="font-mono-ui text-[0.82rem] text-midground">{skill.name}</p>
                      <p className="mt-0.5 line-clamp-2 text-[0.75rem] leading-relaxed text-text-tertiary">
                        {skill.desc || skill.description || 'No description'}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        title="View"
                        aria-label={`View ${skill.name}`}
                        disabled={viewBusy !== null}
                        onClick={() => void openSkill(skill.name)}
                        className="p-1.5 text-text-tertiary hover:text-midground disabled:opacity-40"
                      >
                        {viewBusy === skill.name ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        aria-label={`Delete ${skill.name}`}
                        onClick={() => void remove(skill.name)}
                        className="p-1.5 text-text-tertiary hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </PageBody>

      <Modal
        open={viewing !== null}
        title={viewing?.name || 'Skill'}
        onClose={() => setViewing(null)}
        wide
      >
        {viewing?.desc && <p className="mb-2 text-[0.8rem] text-text-secondary">{viewing.desc}</p>}
        {viewing?.warnings?.length ? (
          <div className="mb-2 border border-warning/50 px-2 py-1.5 text-[0.74rem] text-warning">
            {viewing.warnings.join(' · ')}
          </div>
        ) : null}
        <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words border border-border bg-card px-3 py-2 font-mono-ui text-[0.74rem] leading-relaxed text-text-secondary">
          {viewing?.content || ''}
        </pre>
      </Modal>

      <Modal
        open={createOpen}
        title="New skill"
        onClose={() => setCreateOpen(false)}
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={saving}
              disabled={!newName.trim() || !newContent.trim()}
              onClick={() => void create()}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Name" hint="Lowercase, hyphenated. This is the id the agent loads by.">
            <input
              className="input font-mono-ui"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="fetch-and-summarise"
              autoFocus
            />
          </Field>
          <Field label="Content" hint="Markdown with a short frontmatter description.">
            <textarea
              className={cn('input min-h-[16rem] resize-y font-mono-ui text-[0.75rem] leading-relaxed')}
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              spellCheck={false}
            />
          </Field>
        </div>
      </Modal>
      {confirmNode}
    </>
  )
}
