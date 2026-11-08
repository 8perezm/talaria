import { useCallback, useEffect } from 'react'
import { api } from '@/lib/api'
import { useAppData } from '@/lib/app-data'
import {
  applyTheme,
  loadThemeCache,
  THEME_DEFAULTS,
  THEME_REFRESH_EVENT,
  themeFromFields,
} from '@/lib/theme'

interface FormField {
  key: string
  value?: unknown
}

interface FormResponse {
  fields: FormField[]
}

/* Applies the stored Config -> Theme on every page load and re-applies
   after the Config page saves (THEME_REFRESH_EVENT). Locked views (the
   /login gate) use the last cached theme instead of the stock defaults, so
   signing in does not flash a different font/color scheme. Failures are
   silent: the cached/baked-in tokens in index.css are the fallback. */
export function ThemeApplier() {
  const { authed } = useAppData()

  const apply = useCallback(async () => {
    try {
      const data = await api.get<FormResponse>('/api/config/form')
      if (Array.isArray(data.fields)) applyTheme(themeFromFields(data.fields))
    } catch {
      applyTheme(loadThemeCache() ?? THEME_DEFAULTS)
    }
  }, [])

  useEffect(() => {
    if (!authed) {
      applyTheme(loadThemeCache() ?? THEME_DEFAULTS)
      return
    }
    void apply()
    const handler = () => void apply()
    window.addEventListener(THEME_REFRESH_EVENT, handler)
    return () => window.removeEventListener(THEME_REFRESH_EVENT, handler)
  }, [authed, apply])

  return null
}
