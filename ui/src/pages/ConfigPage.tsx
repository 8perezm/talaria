import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ComponentType } from 'react'
import { useSearchParams } from 'react-router'
import {
  Bot,
  Code,
  Eye,
  EyeOff,
  FileText,
  Filter,
  Lock,
  MessageSquare,
  Palette,
  RotateCw,
  Save,
  Search,
  Settings,
  Settings2,
  ShieldCheck,
  Wifi,
  X,
} from 'lucide-react'
import { api, setToken } from '@/lib/api'
import { useAppData } from '@/lib/app-data'
import { cn } from '@/lib/utils'
import { notifyThemeChanged, THEME_DEFAULTS } from '@/lib/theme'
import { ThemeSection } from '@/pages/ThemeSection'
import {
  Button,
  Chip,
  ErrorNote,
  Field,
  Loading,
  Panel,
  Toggle,
  useConfirm,
  useToast,
} from '@/components/ui'
import { PageBody, PageHeader, StatusChip } from '@/components/Shell'

/* ------------------------------------------------------------------ */
/*  API shapes                                                         */
/* ------------------------------------------------------------------ */

type FieldType =
  | 'string'
  | 'text'
  | 'number'
  | 'boolean'
  | 'select'
  | 'secret'
  | 'readonly'
  | 'list'

interface ConfigField {
  key: string
  category: string
  group?: string
  type: FieldType
  label: string
  description?: string
  placeholder?: string
  min?: number
  max?: number
  step?: number
  options?: string[]
  restart?: boolean
  value?: string | number | boolean
  masked?: string
  has_value?: boolean
}

interface ConfigCategory {
  id: string
  label: string
  description?: string
}

interface ConfigFormResponse {
  path: string
  version: number
  categories: ConfigCategory[]
  fields: ConfigField[]
}

interface ConfigYamlResponse {
  yaml: string
  path: string
  redacted: boolean
  version: number
}

interface SaveResponse {
  ok?: boolean
  error?: string
  restart_required?: boolean
  masked_secrets_preserved?: boolean
  auth_changed?: boolean
  auth_token?: string
}

type Value = string | number | boolean
type Values = Record<string, Value>

/* ------------------------------------------------------------------ */
/*  Categories / icons                                                 */
/* ------------------------------------------------------------------ */

const CATEGORY_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  agent: Bot,
  fallback: ShieldCheck,
  network: Wifi,
  chat: MessageSquare,
  theme: Palette,
  security: Lock,
}

function CategoryIcon({ id, className }: { id: string; className?: string }) {
  const Icon = CATEGORY_ICONS[id] ?? Settings
  return <Icon className={className ?? 'h-3.5 w-3.5'} />
}

function groupFields(fields: ConfigField[]) {
  const groups: Array<{ label: string; fields: ConfigField[] }> = []
  const index = new Map<string, number>()
  for (const field of fields) {
    const label = field.group || 'General'
    let at = index.get(label)
    if (at === undefined) {
      at = groups.length
      index.set(label, at)
      groups.push({ label, fields: [] })
    }
    groups[at].fields.push(field)
  }
  return groups
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export function ConfigPage() {
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const { refreshStatus, refreshConfig } = useAppData()

  const [form, setForm] = useState<ConfigFormResponse | null>(null)
  const [values, setValues] = useState<Values>({})
  const [initial, setInitial] = useState<Values>({})
  const [active, setActive] = useState('')
  const [search, setSearch] = useState('')
  const [mode, setMode] = useState<'form' | 'yaml'>('form')
  const [yamlText, setYamlText] = useState('')
  const [yamlRedacted, setYamlRedacted] = useState(true)
  const [yamlDirty, setYamlDirty] = useState(false)
  const [yamlLoading, setYamlLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [rebooting, setRebooting] = useState(false)
  const [restartPending, setRestartPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [searchParams, setSearchParams] = useSearchParams()

  const applyForm = useCallback((data: ConfigFormResponse) => {
    const next: Values = {}
    for (const field of data.fields) {
      if (field.type === 'readonly') continue
      if (field.type === 'secret') {
        next[field.key] = ''
      } else if (field.type === 'boolean') {
        next[field.key] = Boolean(field.value)
      } else if (field.type === 'number') {
        const n = Number(field.value)
        next[field.key] = Number.isFinite(n) ? n : Number(field.min ?? 0)
      } else {
        next[field.key] = field.value === undefined || field.value === null
          ? ''
          : String(field.value)
      }
    }
    setForm(data)
    setValues(next)
    setInitial(next)
    setActive((prev) => (
      prev && data.categories.some((cat) => cat.id === prev)
        ? prev
        : data.categories[0]?.id ?? ''
    ))
  }, [])

  const loadForm = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<ConfigFormResponse>('/api/config/form')
      applyForm(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read config.yaml')
    } finally {
      setLoading(false)
    }
  }, [applyForm])

  useEffect(() => {
    void loadForm()
  }, [loadForm])

  /* Deep link from the sidebar ("theme" next to Restart): /config?section=theme
     selects that section on arrival, then drops the param. */
  useEffect(() => {
    const want = searchParams.get('section')
    if (!want || !form || !form.categories.some((cat) => cat.id === want)) return
    setActive(want)
    setSearchParams({}, { replace: true })
  }, [form, searchParams, setSearchParams])

  const loadYaml = useCallback(async (reveal: boolean) => {
    setYamlLoading(true)
    try {
      const data = await api.get<ConfigYamlResponse>(
        '/api/config/yaml',
        reveal ? { secrets: 1 } : undefined,
      )
      setYamlText(data.yaml)
      setYamlRedacted(data.redacted)
      setYamlDirty(false)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Could not read config.yaml')
    } finally {
      setYamlLoading(false)
    }
  }, [push])

  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const field of form?.fields ?? []) {
      out[field.category] = (out[field.category] ?? 0) + 1
    }
    return out
  }, [form])

  const query = search.trim().toLowerCase()
  const searching = query.length > 0
  const searchFields = useMemo(() => {
    if (!form || !query) return []
    const labels: Record<string, string> = {}
    for (const cat of form.categories) labels[cat.id] = cat.label
    return form.fields.filter((field) => {
      const haystack = [
        field.key,
        field.label,
        field.description ?? '',
        field.group ?? '',
        labels[field.category] ?? field.category,
      ].join(' ').toLowerCase()
      return haystack.includes(query)
    })
  }, [form, query])

  const activeCategory = form?.categories.find((cat) => cat.id === active)
  const activeFields = useMemo(
    () => (form?.fields ?? []).filter((field) => field.category === active),
    [form, active],
  )
  const restartDirty = useMemo(() => {
    const keys = [
      'network.wifi_ssid',
      'network.wifi_pass',
      'network.mdns_name',
      'network.ap_ssid',
    ]
    return keys.some((key) => values[key] !== initial[key])
  }, [values, initial])

  const setValue = (key: string, next: Value) => {
    setValues((prev) => {
      const out: Values = { ...prev, [key]: next }
      if (key === 'chat.log_max_kb') {
        const max = Number(next)
        const keep = Number(out['chat.log_keep_kb'])
        if (Number.isFinite(max)) {
          const ceiling = Math.max(32, max - 32)
          if (!Number.isFinite(keep) || keep > ceiling) {
            out['chat.log_keep_kb'] = ceiling
          }
        }
      }
      return out
    })
  }

  const resetTheme = () => {
    setValues((prev) => ({
      ...prev,
      'theme.color_scheme': THEME_DEFAULTS.scheme,
      'theme.font_headers': THEME_DEFAULTS.fontHeaders,
      'theme.font_headers_size': THEME_DEFAULTS.fontHeadersSize,
      'theme.font_body': THEME_DEFAULTS.fontBody,
      'theme.font_body_size': THEME_DEFAULTS.fontBodySize,
      'theme.font_mono': THEME_DEFAULTS.fontMono,
      'theme.font_mono_size': THEME_DEFAULTS.fontMonoSize,
    }))
  }

  const saveForm = async () => {
    if (!form) return
    const payload: Values = {}
    for (const field of form.fields) {
      if (field.type === 'readonly') continue
      const value = values[field.key]
      if (field.type === 'secret') {
        if (typeof value === 'string' && value.trim() !== '') payload[field.key] = value
        continue
      }
      if (value === initial[field.key]) continue
      if (field.type === 'number') {
        const number = Number(value)
        if (value === '' || !Number.isFinite(number)) {
          push('err', `${field.label} must be a number`)
          return
        }
        payload[field.key] = number
        continue
      }
      if (field.type === 'boolean') {
        payload[field.key] = Boolean(value)
        continue
      }
      payload[field.key] = value
    }
    if (Object.keys(payload).length === 0) {
      push('info', 'No changes to save')
      return
    }
    setSaving(true)
    try {
      const res = await api.post<SaveResponse>('/api/config/form', { values: payload })
      if (res.error) throw new Error(res.error)
      if (res.auth_changed && res.auth_token) setToken(res.auth_token)
      push('ok', 'Configuration saved')
      if (res.restart_required) {
        setRestartPending(true)
        push('info', 'Restart to apply the network changes')
      }
      await loadForm()
      // The form save rewrote config.yaml; drop any cached raw text so the
      // YAML view reloads instead of resurrecting stale edits.
      setYamlText('')
      setYamlDirty(false)
      await refreshStatus()
      await refreshConfig()
      notifyThemeChanged()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const saveYaml = async () => {
    if (!yamlText.trim()) {
      push('err', 'YAML is empty')
      return
    }
    setSaving(true)
    try {
      const res = await api.post<SaveResponse>('/api/config/yaml', { yaml: yamlText })
      if (res.error) throw new Error(res.error)
      if (res.auth_changed && res.auth_token) setToken(res.auth_token)
      push('ok', res.masked_secrets_preserved
        ? 'config.yaml saved — masked secrets kept'
        : 'config.yaml saved')
      if (res.restart_required) {
        setRestartPending(true)
        push('info', 'Restart to apply the network changes')
      }
      // Keep the editor at the same visibility it had before saving.
      await loadYaml(!yamlRedacted)
      await loadForm()
      await refreshStatus()
      await refreshConfig()
      notifyThemeChanged()
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const toggleMode = () => {
    if (mode === 'form') {
      setMode('yaml')
      if (!yamlText && !yamlLoading) void loadYaml(false)
    } else {
      setMode('form')
    }
  }

  const toggleReveal = async () => {
    if (yamlDirty) {
      const ok = await confirm(
        'Reload the YAML editor?',
        'Your unsaved YAML edits will be discarded.',
      )
      if (!ok) return
    }
    await loadYaml(yamlRedacted)
  }

  const restart = async () => {
    const ok = await confirm(
      'Restart the device',
      'The dashboard reconnects in a few seconds. Config, memory and the chat log are kept.',
    )
    if (!ok) return
    setRebooting(true)
    try {
      await api.post('/api/reboot')
      setRestartPending(false)
      push('info', 'Restarting…')
      setTimeout(() => void refreshStatus(), 5000)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Restart failed')
    } finally {
      setRebooting(false)
    }
  }

  const renderField = (field: ConfigField) => {
    const value = values[field.key]
    const key = field.key
    const numberValue = Number(value)
    const dynamicMax = key === 'chat.log_keep_kb'
      ? Math.max(32, Number(values['chat.log_max_kb'] ?? field.max ?? 4064) - 32)
      : field.max
    const invalidNumber = field.type === 'number' && (
      value === ''
      || !Number.isFinite(numberValue)
      || (field.min !== undefined && numberValue < field.min)
      || (dynamicMax !== undefined && numberValue > dynamicMax)
    )

    if (field.type === 'readonly') {
      const on = Boolean(field.has_value)
      return (
        <Field key={key} label={field.label} hint={field.description}>
          <div className="input flex items-center justify-between gap-2">
            <span className="font-mono-ui text-[0.78rem] text-text-secondary">
              {on ? 'configured' : 'open'}
            </span>
            <Chip tone={on ? 'success' : 'warning'} dot>
              {on ? 'token set' : 'no token'}
            </Chip>
          </div>
        </Field>
      )
    }

    if (field.type === 'boolean') {
      return (
        <div
          key={key}
          className="flex items-start justify-between gap-3 border border-border px-3 py-2.5"
        >
          <div className="min-w-0">
            <span className="field-label mb-0">{field.label}</span>
            {field.description && (
              <p className="mt-0.5 text-[0.72rem] leading-snug text-text-faint">
                {field.description}
              </p>
            )}
          </div>
          <Toggle
            checked={Boolean(value)}
            onChange={(next) => setValue(key, next)}
            label={field.label}
          />
        </div>
      )
    }

    if (field.type === 'secret') {
      const shown = Boolean(showSecrets[key])
      return (
        <Field
          key={key}
          label={field.label}
          hint={(
            <>
              {field.description}
              {field.has_value && field.masked && (
                <span className="mt-0.5 block font-mono-ui text-text-tertiary">
                  stored: {field.masked}
                </span>
              )}
            </>
          )}
        >
          <div className="flex gap-1.5">
            <input
              className="input font-mono-ui text-[0.78rem]"
              type={shown ? 'text' : 'password'}
              value={String(value ?? '')}
              onChange={(e) => setValue(key, e.target.value)}
              placeholder={field.has_value ? 'leave blank to keep' : field.placeholder}
              autoComplete="off"
            />
            <Button
              variant="ghost"
              size="sm"
              title={shown ? 'Hide' : 'Show'}
              onClick={() => setShowSecrets((prev) => ({ ...prev, [key]: !prev[key] }))}
            >
              {shown ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            </Button>
          </div>
        </Field>
      )
    }

    if (field.type === 'number') {
      return (
        <Field
          key={key}
          label={field.label}
          hint={(
            <>
              {field.description}
              {invalidNumber && (
                <span className="ml-1 text-destructive">
                  enter {field.min ?? 0}–{dynamicMax ?? '∞'}
                </span>
              )}
            </>
          )}
        >
          <input
            className={cn('input font-mono-ui text-[0.78rem]', invalidNumber && 'border-destructive/70')}
            type="number"
            min={field.min}
            max={dynamicMax}
            step={field.step}
            value={String(value ?? '')}
            onChange={(e) => setValue(key, e.target.value)}
          />
        </Field>
      )
    }

    if (field.type === 'select') {
      return (
        <Field key={key} label={field.label} hint={field.description}>
          <select
            className="input font-mono-ui text-[0.78rem]"
            value={String(value ?? '')}
            onChange={(e) => setValue(key, e.target.value)}
          >
            {(field.options ?? []).map((option) => (
              <option key={option} value={option}>{option || '(none)'}</option>
            ))}
          </select>
        </Field>
      )
    }

    if (field.type === 'text' || field.type === 'list') {
      return (
        <Field key={key} label={field.label} hint={field.description} >
          <textarea
            className="input min-h-[5rem] resize-y font-mono-ui text-[0.78rem]"
            value={String(value ?? '')}
            onChange={(e) => setValue(key, e.target.value)}
            placeholder={field.placeholder}
          />
        </Field>
      )
    }

    return (
      <Field key={key} label={field.label} hint={field.description}>
        <input
          className="input font-mono-ui text-[0.78rem]"
          value={String(value ?? '')}
          onChange={(e) => setValue(key, e.target.value)}
          placeholder={field.placeholder}
        />
      </Field>
    )
  }

  const renderGroup = (label: string, fields: ConfigField[]) => (
    <section key={label} className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="label-display text-[0.62rem] tracking-[0.14em] text-text-tertiary">
          {label}
        </span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(renderField)}
      </div>
    </section>
  )

  const searchGroups = useMemo(() => {
    if (!form || !searching) return []
    const byCategory = new Map<string, ConfigField[]>()
    for (const field of searchFields) {
      const list = byCategory.get(field.category) ?? []
      list.push(field)
      byCategory.set(field.category, list)
    }
    return form.categories
      .filter((cat) => byCategory.has(cat.id))
      .map((cat) => ({ category: cat, fields: byCategory.get(cat.id) ?? [] }))
  }, [form, searching, searchFields])

  const yamlLines = yamlText ? yamlText.split('\n').length : 0
  const saveBusy = saving && (mode === 'form' || mode === 'yaml')

  return (
    <>
      <PageHeader
        title="Config"
        icon={<Settings className="h-4 w-4" />}
        subtitle={<StatusChip />}
        actions={(
          <>
            {mode === 'form' && (
              <div className="relative w-full min-w-0 sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
                <input
                  className="input h-8 pl-8 pr-7 text-[0.78rem]"
                  placeholder="Search..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search configuration"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    aria-label="Clear search"
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-midground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            )}
          </>
        )}
      />
      <PageBody>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border border-border px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <Settings2 className="h-4 w-4 shrink-0 text-text-tertiary" />
              <code className="min-w-0 flex-1 truncate font-mono-ui text-[0.75rem] text-text-secondary">
                {form?.path ?? 'config.yaml'}
              </code>
              {form && <Chip tone="muted">v{form.version}</Chip>}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {mode === 'yaml' && (
                <>
                  <Chip tone={yamlRedacted ? 'muted' : 'warning'} dot>
                    {yamlRedacted ? 'secrets masked' : 'secrets visible'}
                  </Chip>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={yamlLoading}
                    onClick={() => void toggleReveal()}
                  >
                    {yamlRedacted ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                    {yamlRedacted ? 'Reveal' : 'Mask'}
                  </Button>
                </>
              )}
              <Button
                size="sm"
                variant={mode === 'yaml' ? 'default' : 'ghost'}
                onClick={toggleMode}
              >
                {mode === 'yaml'
                  ? <Settings2 className="h-3 w-3" />
                  : <Code className="h-3 w-3" />}
                {mode === 'yaml' ? 'Form' : 'YAML'}
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={saveBusy}
                disabled={mode === 'form' ? !form : yamlLoading || !yamlText.trim()}
                onClick={() => void (mode === 'form' ? saveForm() : saveYaml())}
              >
                <Save className="h-3 w-3" /> Save
              </Button>
            </div>
          </div>

          {error && <ErrorNote onRetry={() => void loadForm()}>{error}</ErrorNote>}

          {loading && !form && (
            <Panel><Loading label="Reading config.yaml…" /></Panel>
          )}

          {mode === 'yaml' ? (
            <Panel
              title={(
                <span className="flex items-center gap-2">
                  <FileText className="h-3.5 w-3.5" /> Raw YAML configuration
                </span>
              )}
              actions={<Chip tone="muted">{yamlLines} lines</Chip>}
            >
              <p className="border-b border-border px-3.5 py-2 text-[0.72rem] leading-snug text-text-faint">
                Saving replaces the whole file. Masked secrets are preserved;
                press Reveal to edit them.
              </p>
              {yamlLoading ? (
                <Loading label="Reading config.yaml…" />
              ) : (
                <textarea
                  className="min-h-[60vh] w-full resize-y bg-transparent px-3.5 py-3 font-mono-ui text-[0.75rem] leading-relaxed text-text-secondary outline-none"
                  value={yamlText}
                  onChange={(e) => {
                    setYamlText(e.target.value)
                    setYamlDirty(true)
                  }}
                  spellCheck={false}
                  aria-label="Raw YAML configuration"
                />
              )}
            </Panel>
          ) : form ? (
            <div className="flex flex-col gap-3 sm:flex-row">
              <aside aria-label="Config sections" className="w-full shrink-0 sm:w-56">
                <div className="border border-border bg-midground/3 sm:sticky sm:top-4">
                  <div className="hidden items-center gap-2 border-b border-border px-3 py-2 sm:flex">
                    <Filter className="h-3 w-3 text-text-tertiary" />
                    <span className="label-display text-[0.64rem] tracking-[0.12em] text-text-secondary">
                      Filters
                    </span>
                  </div>
                  <div className="hidden px-3 pb-1 pt-2 label-display text-[0.6rem] tracking-[0.12em] text-text-tertiary sm:block">
                    Sections
                  </div>
                  <div className="scrollbar-none flex gap-1 overflow-x-auto p-2 sm:max-h-[calc(100vh-16rem)] sm:flex-col sm:gap-px sm:overflow-y-auto">
                    {form.categories.map((cat) => {
                      const isActive = !searching && active === cat.id
                      return (
                        <button
                          key={cat.id}
                          type="button"
                          onClick={() => {
                            setSearch('')
                            setActive(cat.id)
                          }}
                          aria-current={isActive ? 'page' : undefined}
                          className={cn(
                            'group/section relative flex items-center gap-2 whitespace-nowrap px-2 py-1.5 text-left text-[0.75rem] transition-colors',
                            isActive
                              ? 'bg-midground/10 text-midground'
                              : 'text-text-secondary hover:bg-midground/5 hover:text-midground',
                          )}
                        >
                          {isActive && (
                            <span aria-hidden className="absolute bottom-0 left-0 top-0 w-px bg-midground" />
                          )}
                          <CategoryIcon id={cat.id} className="h-3.5 w-3.5 shrink-0" />
                          <span className="flex-1 truncate">{cat.label}</span>
                          <span
                            className={cn(
                              'tabular-nums text-[0.68rem]',
                              isActive ? 'text-midground/80' : 'text-text-faint',
                            )}
                          >
                            {counts[cat.id] ?? 0}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </aside>

              <div className="min-w-0 flex-1">
                {searching ? (
                  <Panel
                    title={(
                      <span className="flex items-center gap-2">
                        <Search className="h-3.5 w-3.5" /> Search results
                      </span>
                    )}
                    actions={<Chip tone="muted">{searchFields.length} fields</Chip>}
                    bodyClassName="flex flex-col gap-4 px-3.5 py-4"
                  >
                    {searchFields.length === 0 ? (
                      <p className="py-8 text-center text-[0.8rem] text-text-faint">
                        No fields match “{search}”.
                      </p>
                    ) : searchGroups.map((group) => (
                      <section key={group.category.id} className="flex flex-col gap-3">
                        <div className="flex items-center gap-2">
                          <CategoryIcon id={group.category.id} className="h-3.5 w-3.5 text-text-tertiary" />
                          <span className="label-display text-[0.62rem] tracking-[0.14em] text-text-tertiary">
                            {group.category.label}
                          </span>
                          <div className="h-px flex-1 bg-border" />
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {group.fields.map(renderField)}
                        </div>
                      </section>
                    ))}
                  </Panel>
                ) : (
                  <Panel
                    title={(
                      <span className="flex items-center gap-2">
                        <CategoryIcon id={active} />
                        {activeCategory?.label ?? 'Config'}
                      </span>
                    )}
                    actions={<Chip tone="muted">{activeFields.length} fields</Chip>}
                    bodyClassName="flex flex-col gap-5 px-3.5 py-4"
                  >
                    {activeCategory?.description && (
                      <p className="text-[0.78rem] leading-relaxed text-text-faint">
                        {activeCategory.description}
                      </p>
                    )}
                    {active === 'theme' ? (
                      <ThemeSection
                        fields={activeFields}
                        values={values}
                        setValue={setValue}
                        onReset={resetTheme}
                      />
                    ) : (
                      groupFields(activeFields).map((group) => renderGroup(group.label, group.fields))
                    )}
                    {active === 'network' && (
                      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
                        <p className="text-[0.72rem] leading-snug text-text-faint">
                          Network changes apply after a restart.
                          {(restartDirty || restartPending) && ' Restart required to apply network edits.'}
                        </p>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={rebooting}
                          onClick={() => void restart()}
                        >
                          <RotateCw className="h-3 w-3" /> Restart
                        </Button>
                      </div>
                    )}
                  </Panel>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </PageBody>
      {confirmNode}
    </>
  )
}
