import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, RotateCcw } from 'lucide-react'
import { Button, Field, useToast } from '@/components/ui'
import { cn } from '@/lib/utils'
import {
  ALL_GOOGLE_FONTS,
  COLOR_SCHEMES,
  SYSTEM_FONT,
  THEME_DEFAULTS,
  applyTheme,
  fontStack,
  googleFontsHref,
  type ThemeFont,
} from '@/lib/theme'

export type ThemeValue = string | number | boolean

interface ThemeFieldDef {
  key: string
  label: string
  description?: string
  options?: string[]
  min?: number
  max?: number
  step?: number
}

interface ThemeSectionProps {
  fields: ThemeFieldDef[]
  values: Record<string, ThemeValue>
  setValue: (key: string, next: ThemeValue) => void
  onReset: () => void
}

function defFor(fields: ThemeFieldDef[], key: string): ThemeFieldDef | undefined {
  return fields.find((f) => f.key === key)
}

function strVal(values: Record<string, ThemeValue>, key: string, fallback: string): string {
  const v = values[key]
  return typeof v === 'string' && v ? v : fallback
}

function numVal(values: Record<string, ThemeValue>, key: string, fallback: number): number {
  const v = values[key]
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

/* ------------------------------------------------------------------ */
/*  Searchable font picker (screenshot-style: name + kind + pangram)   */
/* ------------------------------------------------------------------ */

function FontPicker({
  label,
  hint,
  fonts,
  value,
  onChange,
}: {
  label: string
  hint?: string
  fonts: ThemeFont[]
  value: string
  onChange: (name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const current = fonts.find((f) => f.name === value)
  const q = query.trim().toLowerCase()
  const matches = q
    ? fonts.filter((f) => f.name.toLowerCase().includes(q))
    : fonts

  return (
    <Field label={label} hint={hint}>
      <div className="relative">
        <button
          type="button"
          onClick={() => {
            setQuery('')
            setOpen((v) => !v)
          }}
          aria-haspopup="listbox"
          aria-expanded={open}
          className="input flex items-center justify-between gap-2 text-left"
        >
          <span
            className="min-w-0 flex-1 truncate text-[0.85rem]"
            style={{ fontFamily: fontStack(value, current?.kind ?? 'sans') }}
          >
            {value || SYSTEM_FONT}
          </span>
          <span className="chip shrink-0">{current?.kind === 'mono' ? 'monospace' : 'sans-serif'}</span>
          <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-text-faint transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <>
            <button
              type="button"
              aria-hidden
              tabIndex={-1}
              className="fixed inset-0 z-[60] cursor-default"
              onClick={() => setOpen(false)}
            />
            <div
              role="listbox"
              className="absolute left-0 right-0 top-full z-[61] mt-1 max-h-72 overflow-y-auto border border-border bg-background-base shadow-[0_18px_50px_rgba(0,0,0,0.55)]"
            >
              <div className="sticky top-0 border-b border-border bg-background-base p-1.5">
                <input
                  className="input h-8 text-[0.78rem]"
                  placeholder="Search fonts…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label={`Search ${label}`}
                />
              </div>
              <button
                type="button"
                role="option"
                aria-selected={value === SYSTEM_FONT}
                onClick={() => {
                  onChange(SYSTEM_FONT)
                  setOpen(false)
                }}
                className={cn(
                  'block w-full px-3 py-2 text-left hover:bg-midground/8',
                  value === SYSTEM_FONT ? 'bg-midground/10 text-midground' : 'text-text-secondary',
                )}
              >
                <span className="block text-[0.85rem]">{SYSTEM_FONT}</span>
                <span className="block text-[0.68rem] text-text-faint">Built-in stack — works offline</span>
              </button>
              {matches.map((font) => (
                <button
                  key={font.name}
                  type="button"
                  role="option"
                  aria-selected={font.name === value}
                  onClick={() => {
                    onChange(font.name)
                    setOpen(false)
                  }}
                  className={cn(
                    'block w-full px-3 py-2 text-left hover:bg-midground/8',
                    font.name === value ? 'bg-midground/10' : 'text-text-secondary',
                  )}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[0.85rem] text-midground" style={{ fontFamily: fontStack(font.name, font.kind) }}>
                      {font.name}
                    </span>
                    <span className="shrink-0 text-[0.62rem] uppercase tracking-[0.1em] text-text-faint">
                      {font.kind === 'mono' ? 'monospace' : 'sans-serif'}
                    </span>
                  </span>
                  <span className="block truncate text-[0.72rem] text-text-tertiary" style={{ fontFamily: fontStack(font.name, font.kind) }}>
                    The quick brown fox jumps over 0123456789
                  </span>
                </button>
              ))}
              {matches.length === 0 && (
                <p className="px-3 py-4 text-center text-[0.78rem] text-text-faint">
                  No fonts match “{query}”.
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </Field>
  )
}

/* ------------------------------------------------------------------ */
/*  Slider + numeric input pair                                        */
/* ------------------------------------------------------------------ */

function SizeRow({
  label,
  hint,
  min,
  max,
  value,
  onChange,
}: {
  label: string
  hint?: string
  min: number
  max: number
  value: number
  onChange: (next: number) => void
}) {
  const clamp = (n: number) => (Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : value)
  return (
    <Field label={label} hint={hint}>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(clamp(Number(e.target.value)))}
        className="w-full"
        aria-label={label}
      />
      <div className="mt-1.5 flex items-center gap-2">
        <input
          className="input w-20 font-mono-ui text-[0.78rem]"
          type="number"
          min={min}
          max={max}
          step={1}
          value={value}
          onChange={(e) => onChange(clamp(Number(e.target.value)))}
          aria-label={`${label} in pixels`}
        />
        <span className="text-[0.72rem] text-text-faint">px</span>
      </div>
    </Field>
  )
}

/* ------------------------------------------------------------------ */
/*  Theme section                                                      */
/* ------------------------------------------------------------------ */

export function ThemeSection({ fields, values, setValue, onReset }: ThemeSectionProps) {
  const { push } = useToast()

  const theme = useMemo(
    () => ({
      scheme: strVal(values, 'theme.color_scheme', THEME_DEFAULTS.scheme),
      fontHeaders: strVal(values, 'theme.font_headers', THEME_DEFAULTS.fontHeaders),
      fontHeadersSize: numVal(values, 'theme.font_headers_size', THEME_DEFAULTS.fontHeadersSize),
      fontBody: strVal(values, 'theme.font_body', THEME_DEFAULTS.fontBody),
      fontBodySize: numVal(values, 'theme.font_body_size', THEME_DEFAULTS.fontBodySize),
      fontMono: strVal(values, 'theme.font_mono', THEME_DEFAULTS.fontMono),
      fontMonoSize: numVal(values, 'theme.font_mono_size', THEME_DEFAULTS.fontMonoSize),
    }),
    [values],
  )

  /* Instant preview while editing; the main Save button persists to config.yaml.
     cache:false — an unsaved preview must not become the next boot theme. */
  useEffect(() => {
    applyTheme(theme, { cache: false })
  }, [theme])

  /* Load every Google Font once so dropdown previews render faithfully. */
  useEffect(() => {
    const id = 'theme-font-previews'
    if (!document.getElementById(id)) {
      const link = document.createElement('link')
      link.id = id
      link.rel = 'stylesheet'
      link.href = googleFontsHref(ALL_GOOGLE_FONTS.map((f) => f.name))
      document.head.appendChild(link)
    }
    return () => {
      document.getElementById(id)?.remove()
    }
  }, [])

  const headersDef = defFor(fields, 'theme.font_headers_size')
  const bodyDef = defFor(fields, 'theme.font_body_size')
  const monoDef = defFor(fields, 'theme.font_mono_size')

  return (
    <div className="flex flex-col gap-5">
      {/* ---- color schemes ---- */}
      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="label-display text-[0.62rem] tracking-[0.14em] text-text-tertiary">
            Color scheme
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {COLOR_SCHEMES.map((scheme) => {
            const selected = theme.scheme === scheme.id
            return (
              <button
                key={scheme.id}
                type="button"
                onClick={() => setValue('theme.color_scheme', scheme.id)}
                aria-pressed={selected}
                className={cn(
                  'flex items-center gap-2.5 border px-2.5 py-2 text-left transition-colors',
                  selected ? 'border-midground' : 'border-border hover:border-midground/40',
                )}
              >
                <span
                  className="flex h-8 w-12 shrink-0 items-end justify-end border border-border p-1"
                  style={{ background: scheme.bg }}
                >
                  <span className="h-3 w-3" style={{ background: scheme.mid }} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn('block truncate text-[0.8rem]', selected ? 'text-midground' : 'text-text-secondary')}>
                    {scheme.name}
                  </span>
                  <span className="block text-[0.64rem] uppercase tracking-[0.12em] text-text-faint">
                    {scheme.light ? 'light' : 'dark'}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </section>

      {/* ---- fonts ---- */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="label-display text-[0.62rem] tracking-[0.14em] text-text-tertiary">
            Fonts
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <FontPicker
            label="Headers font"
            hint="Display font for headings and labels."
            fonts={ALL_GOOGLE_FONTS.filter((f) => f.kind === 'sans')}
            value={theme.fontHeaders}
            onChange={(name) => setValue('theme.font_headers', name)}
          />
          <SizeRow
            label="Headers size"
            hint="Panel titles and labels."
            min={headersDef?.min ?? 10}
            max={headersDef?.max ?? 32}
            value={theme.fontHeadersSize}
            onChange={(n) => setValue('theme.font_headers_size', n)}
          />
          <FontPicker
            label="Default font"
            hint="Body text, buttons, inputs and tables."
            fonts={ALL_GOOGLE_FONTS.filter((f) => f.kind === 'sans')}
            value={theme.fontBody}
            onChange={(name) => setValue('theme.font_body', name)}
          />
          <SizeRow
            label="Default size"
            hint="Base size — the whole layout scales with it."
            min={bodyDef?.min ?? 10}
            max={bodyDef?.max ?? 24}
            value={theme.fontBodySize}
            onChange={(n) => setValue('theme.font_body_size', n)}
          />
          <FontPicker
            label="Terminal font"
            hint="Code, logs and the file editor."
            fonts={ALL_GOOGLE_FONTS.filter((f) => f.kind === 'mono')}
            value={theme.fontMono}
            onChange={(name) => setValue('theme.font_mono', name)}
          />
          <SizeRow
            label="Terminal size"
            hint="Code, logs and preformatted blocks."
            min={monoDef?.min ?? 10}
            max={monoDef?.max ?? 24}
            value={theme.fontMonoSize}
            onChange={(n) => setValue('theme.font_mono_size', n)}
          />
        </div>
        <p className="text-[0.7rem] leading-relaxed text-text-faint">
          Google Fonts load on demand in this browser only. Offline, everything falls back
          to the built-in stacks. Press Save to keep these settings in config.yaml.
        </p>
      </section>

      {/* ---- live preview ---- */}
      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="label-display text-[0.62rem] tracking-[0.14em] text-text-tertiary">
            Preview
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="border border-border px-3.5 py-3">
          <p style={{ fontFamily: fontStack(theme.fontHeaders, 'sans'), fontSize: theme.fontHeadersSize + 2 }}>
            Project overview
          </p>
          <p className="mt-1 text-text-faint" style={{ fontFamily: fontStack(theme.fontHeaders, 'sans'), fontSize: Math.max(10, theme.fontHeadersSize - 2) }}>
            Headers, body and terminal type at the sizes above.
          </p>
          <p className="mt-2 leading-relaxed" style={{ fontFamily: fontStack(theme.fontBody, 'sans'), fontSize: theme.fontBodySize }}>
            The quick brown fox jumps over the lazy dog. Body copy, buttons, inputs and
            tables all follow the Default font and size — 0123456789.
          </p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="primary" onClick={() => push('info', 'Preview only — press Save to keep the theme')}>Button</Button>
            <Button size="sm" variant="ghost" onClick={() => push('info', 'Preview only — press Save to keep the theme')}>Ghost</Button>
          </div>
          <pre
            className="mt-2 overflow-x-auto p-2.5 leading-relaxed"
            style={{
              background: '#101414',
              color: '#e8e4da',
              fontFamily: fontStack(theme.fontMono, 'mono'),
              fontSize: theme.fontMonoSize,
            }}
          >
            {`$ tail logs --project demo\nNAME    STATUS    PORTS\ndemo    Running   22, 80, 443`}
          </pre>
        </div>
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" onClick={onReset}>
            <RotateCcw className="h-3 w-3" /> Reset to defaults
          </Button>
        </div>
      </section>
    </div>
  )
}
