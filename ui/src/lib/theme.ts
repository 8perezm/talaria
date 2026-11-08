/* ------------------------------------------------------------------ */
/*  Theme engine                                                        */
/*                                                                     */
/*  Color schemes + Google Fonts applied as runtime CSS variables, so   */
/*  the compiled bundle never changes: the stock look stays baked into  */
/*  index.css and these overrides only diverge when the user picks      */
/*  something in Config -> Theme (persisted in config.yaml).            */
/*                                                                     */
/*  NOTE — external-font carve-out: this module is the ONE place that   */
/*  may reference the Google Fonts CDN (see test_no_external_fetches).  */
/*  Fonts load on demand in the browser only; offline the system stacks  */
/*  below render instead, so the dashboard never depends on them.        */
/* ------------------------------------------------------------------ */

export const THEME_REFRESH_EVENT = 'talaria-theme'

export function notifyThemeChanged() {
  try {
    window.dispatchEvent(new Event(THEME_REFRESH_EVENT))
  } catch {
    /* non-browser (tests) */
  }
}

export interface ColorScheme {
  id: string
  name: string
  light: boolean
  bg: string
  mid: string
  success: string
  warning: string
  destructive: string
}

export const COLOR_SCHEMES: ColorScheme[] = [
  { id: 'talaria-dark', name: 'Talaria', light: false, bg: '#041c1c', mid: '#ffe6cb', success: '#4ade80', warning: '#ffbd38', destructive: '#fb2c36' },
  { id: 'midnight', name: 'Midnight', light: false, bg: '#0b1026', mid: '#9fb4ff', success: '#4ade80', warning: '#ffbd38', destructive: '#fb5e5e' },
  { id: 'forest', name: 'Forest', light: false, bg: '#0b1f16', mid: '#c4f0d0', success: '#4ade80', warning: '#ffd166', destructive: '#ff7b7b' },
  { id: 'ember', name: 'Ember', light: false, bg: '#211009', mid: '#ffc9a3', success: '#7ddf9a', warning: '#ffbd38', destructive: '#ff6b5e' },
  { id: 'graphite', name: 'Graphite', light: false, bg: '#14161b', mid: '#dfe3ea', success: '#4ade80', warning: '#ffbd38', destructive: '#fb5e5e' },
  { id: 'parchment', name: 'Parchment', light: true, bg: '#f6f1e5', mid: '#22332a', success: '#15803d', warning: '#b45309', destructive: '#b91c1c' },
  { id: 'glacier', name: 'Glacier', light: true, bg: '#eef4f9', mid: '#17334e', success: '#15803d', warning: '#b45309', destructive: '#b91c1c' },
  { id: 'blush', name: 'Blush', light: true, bg: '#faf0ee', mid: '#5d2227', success: '#15803d', warning: '#b45309', destructive: '#b91c1c' },
  { id: 'sandstone', name: 'Sandstone', light: true, bg: '#f3ecdd', mid: '#4d3d1c', success: '#3f6212', warning: '#92400e', destructive: '#b91c1c' },
  { id: 'paper', name: 'Paper', light: true, bg: '#ffffff', mid: '#161616', success: '#15803d', warning: '#b45309', destructive: '#dc2626' },
]

export const SYSTEM_FONT = 'System Default'

export interface ThemeFont {
  name: string
  kind: 'sans' | 'mono'
}

/* 30 Google Fonts: 24 sans (headers + body) + 6 mono (terminal). */
export const SANS_FONTS: ThemeFont[] = [
  { name: 'Inter', kind: 'sans' },
  { name: 'Roboto', kind: 'sans' },
  { name: 'Open Sans', kind: 'sans' },
  { name: 'Lato', kind: 'sans' },
  { name: 'Montserrat', kind: 'sans' },
  { name: 'Poppins', kind: 'sans' },
  { name: 'Raleway', kind: 'sans' },
  { name: 'Ubuntu', kind: 'sans' },
  { name: 'Nunito', kind: 'sans' },
  { name: 'Manrope', kind: 'sans' },
  { name: 'DM Sans', kind: 'sans' },
  { name: 'Work Sans', kind: 'sans' },
  { name: 'Fira Sans', kind: 'sans' },
  { name: 'Rubik', kind: 'sans' },
  { name: 'Outfit', kind: 'sans' },
  { name: 'Space Grotesk', kind: 'sans' },
  { name: 'IBM Plex Sans', kind: 'sans' },
  { name: 'Karla', kind: 'sans' },
  { name: 'Heebo', kind: 'sans' },
  { name: 'Cabin', kind: 'sans' },
  { name: 'Barlow', kind: 'sans' },
  { name: 'Lexend', kind: 'sans' },
  { name: 'Mulish', kind: 'sans' },
  { name: 'Source Sans 3', kind: 'sans' },
]

export const MONO_FONTS: ThemeFont[] = [
  { name: 'Roboto Mono', kind: 'mono' },
  { name: 'JetBrains Mono', kind: 'mono' },
  { name: 'Fira Code', kind: 'mono' },
  { name: 'Source Code Pro', kind: 'mono' },
  { name: 'IBM Plex Mono', kind: 'mono' },
  { name: 'Inconsolata', kind: 'mono' },
]

export const ALL_GOOGLE_FONTS: ThemeFont[] = [...SANS_FONTS, ...MONO_FONTS]

const SANS_FALLBACK = `system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`
const MONO_FALLBACK = `ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace`

export function fontStack(name: string | undefined, kind: 'sans' | 'mono'): string {
  const fallback = kind === 'mono' ? MONO_FALLBACK : SANS_FALLBACK
  if (!name || name === SYSTEM_FONT) return fallback
  return `'${name}', ${fallback}`
}

function css2Href(names: string[]): string {
  const fams = names.map((n) => `family=${n.replace(/ /g, '+')}:wght@400;500;700`).join('&')
  return `https://fonts.googleapis.com/css2?${fams}&display=swap`
}

/* Public for the ThemeSection preview loader (all families at once). */
export function googleFontsHref(names: string[]): string {
  return css2Href(names)
}

const LINK_ID = 'theme-fonts'

/* Keep one <link> carrying exactly the selected Google Fonts. */
function ensureFontLink(names: string[]) {
  if (typeof document === 'undefined') return
  const prev = document.getElementById(LINK_ID)
  if (names.length === 0) {
    if (prev) prev.remove()
    return
  }
  const href = css2Href(names)
  if (prev) {
    if (prev.getAttribute('href') !== href) prev.setAttribute('href', href)
    return
  }
  const link = document.createElement('link')
  link.id = LINK_ID
  link.rel = 'stylesheet'
  link.href = href
  document.head.appendChild(link)
}

export interface ThemeValues {
  scheme: string
  fontHeaders: string
  fontHeadersSize: number
  fontBody: string
  fontBodySize: number
  fontMono: string
  fontMonoSize: number
}

export const THEME_DEFAULTS: ThemeValues = {
  scheme: 'graphite',
  fontHeaders: 'Poppins',
  fontHeadersSize: 15,
  fontBody: 'Space Grotesk',
  fontBodySize: 15,
  fontMono: 'JetBrains Mono',
  fontMonoSize: 13,
}

/* ------------------------------------------------------------------ */
/*  First-paint cache                                                   */
/*                                                                     */
/*  applyTheme() runs after an /api/config/form round trip, which on    */
/*  this device lands ~0.5-1.5s after the bundle boots. Without a       */
/*  cache every page paints once in the stock stack and visibly swaps   */
/*  fonts afterwards. So the last applied values are kept in            */
/*  localStorage and re-applied synchronously from main.tsx BEFORE the  */
/*  first React render; the API fetch then reconciles them.            */
/* ------------------------------------------------------------------ */

const THEME_CACHE_KEY = 'talaria_theme'

function coerceTheme(raw: unknown): ThemeValues {
  if (!raw || typeof raw !== 'object') return { ...THEME_DEFAULTS }
  const src = raw as Record<string, unknown>
  const str = (key: keyof ThemeValues, fallback: string): string => {
    const v = src[key]
    return typeof v === 'string' && v ? v : fallback
  }
  const num = (key: keyof ThemeValues, fallback: number): number => {
    const v = Number(src[key])
    return Number.isFinite(v) && v > 0 ? v : fallback
  }
  return {
    scheme: str('scheme', THEME_DEFAULTS.scheme),
    fontHeaders: str('fontHeaders', THEME_DEFAULTS.fontHeaders),
    fontHeadersSize: num('fontHeadersSize', THEME_DEFAULTS.fontHeadersSize),
    fontBody: str('fontBody', THEME_DEFAULTS.fontBody),
    fontBodySize: num('fontBodySize', THEME_DEFAULTS.fontBodySize),
    fontMono: str('fontMono', THEME_DEFAULTS.fontMono),
    fontMonoSize: num('fontMonoSize', THEME_DEFAULTS.fontMonoSize),
  }
}

export function saveThemeCache(v: ThemeValues) {
  try {
    localStorage.setItem(THEME_CACHE_KEY, JSON.stringify(v))
  } catch {
    /* private mode / tests */
  }
}

export function loadThemeCache(): ThemeValues | null {
  try {
    const raw = localStorage.getItem(THEME_CACHE_KEY)
    if (!raw) return null
    return coerceTheme(JSON.parse(raw))
  } catch {
    return null
  }
}

/* Call once before the first render (main.tsx). Uses the cached theme when
   there is one, otherwise the stock tokens already baked into index.css. */
export function applyBootTheme() {
  const cached = loadThemeCache()
  applyTheme(cached ?? THEME_DEFAULTS)
}

export function applyTheme(v: ThemeValues, options?: { cache?: boolean }) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const scheme = COLOR_SCHEMES.find((s) => s.id === v.scheme) ?? COLOR_SCHEMES[0]
  root.style.setProperty('--background-base', scheme.bg)
  root.style.setProperty('--midground-base', scheme.mid)
  root.style.setProperty('--color-success', scheme.success)
  root.style.setProperty('--color-warning', scheme.warning)
  root.style.setProperty('--color-destructive', scheme.destructive)
  root.style.colorScheme = scheme.light ? 'light' : 'dark'
  root.style.setProperty('--theme-font-display', fontStack(v.fontHeaders, 'sans'))
  root.style.setProperty('--theme-font-sans', fontStack(v.fontBody, 'sans'))
  root.style.setProperty('--theme-font-mono', fontStack(v.fontMono, 'mono'))
  root.style.setProperty('--theme-base-size', `${v.fontBodySize}px`)
  // Size vars only diverge from stock when changed: with defaults the CSS
  // fallbacks reproduce the baked-in look pixel-for-pixel.
  if (v.fontHeadersSize !== THEME_DEFAULTS.fontHeadersSize) {
    root.style.setProperty('--theme-headers-size', `${v.fontHeadersSize}px`)
  } else {
    root.style.removeProperty('--theme-headers-size')
  }
  if (v.fontMonoSize !== THEME_DEFAULTS.fontMonoSize) {
    root.style.setProperty('--theme-mono-size', `${v.fontMonoSize}px`)
  } else {
    root.style.removeProperty('--theme-mono-size')
  }
  const needed = [v.fontHeaders, v.fontBody, v.fontMono].filter(
    (f): f is string => !!f && f !== SYSTEM_FONT,
  )
  ensureFontLink([...new Set(needed)])
  // Unsaved Config -> Theme previews must not become the boot theme.
  if (options?.cache !== false) saveThemeCache(v)
}

/* Read theme.* keys out of a /api/config/form payload. */
export function themeFromFields(fields: Array<{ key: string; value?: unknown }>): ThemeValues {
  const get = (key: string, fallback: string | number): string | number => {
    const found = fields.find((f) => f.key === key)?.value
    if (found === undefined || found === null || found === '') return fallback
    return typeof fallback === 'number' ? Number(found) || fallback : String(found)
  }
  return {
    scheme: String(get('theme.color_scheme', THEME_DEFAULTS.scheme)),
    fontHeaders: String(get('theme.font_headers', THEME_DEFAULTS.fontHeaders)),
    fontHeadersSize: Number(get('theme.font_headers_size', THEME_DEFAULTS.fontHeadersSize)),
    fontBody: String(get('theme.font_body', THEME_DEFAULTS.fontBody)),
    fontBodySize: Number(get('theme.font_body_size', THEME_DEFAULTS.fontBodySize)),
    fontMono: String(get('theme.font_mono', THEME_DEFAULTS.fontMono)),
    fontMonoSize: Number(get('theme.font_mono_size', THEME_DEFAULTS.fontMonoSize)),
  }
}
