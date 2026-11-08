import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 18422 -> "18.0 KB" ; MicroPython byte counts are large and noisy. */
export function bytes(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

/** Compact heap readout, matching the sidebar's dense style. */
export function heap(n: number | undefined | null): string {
  if (!n) return '—'
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}M`
  return `${Math.round(n / 1024)}K`
}

export function uptime(seconds: number | undefined | null): string {
  if (!seconds || seconds < 0) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s % 60}s`
  return `${s}s`
}

/** "2m ago" / "yesterday" — mirrors the upstream sessions list. */
export function relativeTime(epochSeconds: number | undefined | null): string {
  if (!epochSeconds) return '—'
  // MicroPython epoch is 2000-01-01; values below 1e9 are device seconds.
  const now = Math.floor(Date.now() / 1000)
  let ts = epochSeconds
  if (epochSeconds > 0 && epochSeconds < 1_000_000_000) {
    ts = epochSeconds + 946_684_800 // 2000-01-01 -> 1970-01-01
  }
  // Files written before the RTC was ever set carry a 2000-era stamp; showing
  // "01/01/2000" reads as a bug, so treat anything that old as unknown.
  if (ts < 978_307_200) return '—'
  const diff = now - ts
  if (diff < 0) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 172800) return 'yesterday'
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`
  return new Date(ts * 1000).toLocaleDateString()
}

export function pct(value: number, total: number): number {
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)))
}

export function maskSecret(value: string | undefined | null): string {
  if (!value) return '—'
  if (value.length <= 8) return '•'.repeat(value.length)
  return `${value.slice(0, 3)}${'•'.repeat(Math.min(12, value.length - 5))}${value.slice(-2)}`
}
