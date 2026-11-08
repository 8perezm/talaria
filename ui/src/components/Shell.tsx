import { useEffect, useState } from 'react'
import type { ComponentType, ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import {
  BarChart3,
  BookOpen,
  Clock,
  Cpu,
  FileText,
  FolderOpen,
  KeyRound,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Radio,
  RotateCw,
  Settings,
  Terminal,
  Wrench,
  X,
  Zap,
  Power,
  Lock,
  Unlock,
  LayoutGrid,
} from 'lucide-react'
import { cn, heap, uptime } from '@/lib/utils'
import { useAppData } from '@/lib/app-data'
import { Button, Chip, useToast } from '@/components/ui'
import { api } from '@/lib/api'

export interface NavItem {
  path: string
  label: string
  icon: ComponentType<{ className?: string }>
}

export const NAV: NavItem[] = [
  { path: '/', label: 'Chat', icon: Terminal },
  { path: '/sessions', label: 'Sessions', icon: MessageSquare },
  { path: '/files', label: 'Files', icon: FolderOpen },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { path: '/models', label: 'Models', icon: Cpu },
  { path: '/logs', label: 'Logs', icon: FileText },
  { path: '/cron', label: 'Cron', icon: Clock },
  { path: '/skills', label: 'Skills', icon: Zap },
  { path: '/tools', label: 'Tools', icon: Wrench },
  { path: '/channels', label: 'Channels', icon: Radio },
  { path: '/config', label: 'Config', icon: Settings },
  { path: '/keys', label: 'Keys', icon: KeyRound },
  { path: '/system', label: 'System', icon: LayoutGrid },
  { path: '/docs', label: 'Documentation', icon: BookOpen },
]

const COLLAPSED_KEY = 'hermes-sidebar-collapsed'

export function Shell({ children }: { children: ReactNode }) {
  const { status, authed, online, lock } = useAppData()
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === 'true'
    } catch {
      return false
    }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(collapsed))
    } catch {
      /* ignore */
    }
  }, [collapsed])

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!mobileOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [mobileOpen])

  const gatewayState = !online
    ? { label: 'Offline', tone: 'danger' as const }
    : status?.wifi_connected === false
      ? { label: 'No WiFi', tone: 'warning' as const }
      : authed
        ? { label: 'Running', tone: 'success' as const }
        : { label: 'Locked', tone: 'warning' as const }

  return (
    <div
      data-shell="1"
      className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base text-text-primary antialiased"
    >
      {/* ---------- mobile header ---------- */}
      <header className="fixed left-0 right-0 top-0 z-40 flex min-h-14 items-center gap-2 border-b border-border bg-background-base px-4 py-2 lg:hidden">
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
          className="p-1.5 text-text-secondary hover:text-midground"
        >
          <Menu className="h-5 w-5" />
        </button>
        <span className="label-display text-[0.95rem] leading-[0.95] tracking-[0.05em] text-midground">
          Hermes Agent
        </span>
      </header>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-black/70 lg:hidden"
        />
      )}

      <div aria-hidden className="h-14 shrink-0 lg:hidden" />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1">
          {/* ---------- sidebar ---------- */}
          <aside
            id="app-sidebar"
            aria-label="Navigation"
            className={cn(
              'fixed left-0 top-0 z-50 flex h-dvh max-h-dvh w-60 min-h-0 flex-col font-sans',
              'border-r border-border bg-background-base',
              'transition-[transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]',
              mobileOpen ? 'translate-x-0' : '-translate-x-full',
              'lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden',
              'lg:transition-[width] lg:duration-300 lg:ease-[cubic-bezier(0.23,1,0.32,1)]',
              collapsed && 'lg:w-14',
            )}
          >
            {/* brand row */}
            <div
              className={cn(
                'flex h-14 shrink-0 items-center border-b border-border',
                collapsed ? 'lg:justify-center lg:px-0' : 'justify-between px-3',
              )}
            >
              <button
                type="button"
                onClick={() => navigate('/')}
                className={cn(
                  'label-display text-left text-[1.02rem] font-bold leading-[0.95] tracking-[0.0525rem] text-midground',
                  collapsed && 'lg:hidden',
                )}
              >
                Hermes
                <br />
                Agent
              </button>

              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation"
                className="p-1.5 text-text-secondary hover:text-midground lg:hidden"
              >
                <X className="h-4 w-4" />
              </button>

              <button
                type="button"
                onClick={() => setCollapsed((v) => !v)}
                aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
                className="hidden p-1.5 text-text-secondary hover:text-midground lg:block"
              >
                {collapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </button>
            </div>

            {/* scope / profile row — the device is the "profile" */}
            <div className={cn('border-b border-border', collapsed && 'lg:hidden')}>
              <button
                type="button"
                onClick={() => navigate('/system')}
                className="flex w-full items-center gap-1.5 border border-border px-1.5 py-1 text-left text-[0.72rem] text-midground hover:bg-midground/6"
              >
                <LayoutGrid className="h-3 w-3 shrink-0 text-text-tertiary" />
                <span className="min-w-0 flex-1 truncate">
                  this device ({status?.ip || 'esp32'})
                </span>
                <span className="text-text-faint">▾</span>
              </button>
            </div>

            {/* nav */}
            <nav
              className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden border-t border-border/60 py-1.5"
              aria-label="Navigation"
            >
              <ul className="flex flex-col">
                {NAV.map((item) => (
                  <SidebarNavLink
                    key={item.path}
                    item={item}
                    collapsed={collapsed}
                    onNavigate={() => setMobileOpen(false)}
                  />
                ))}
              </ul>
            </nav>

            {/* system block */}
            <div className={cn('border-t border-border px-3 py-2', collapsed && 'lg:hidden')}>
              <p className="label-display mb-1 text-[0.6rem] tracking-[0.14em] text-text-faint">
                System
              </p>
              <p className="text-[0.72rem] leading-snug text-text-secondary">
                <span className="text-text-faint">Gateway Status: </span>
                <span
                  className={cn(
                    'font-medium',
                    gatewayState.tone === 'success' && 'text-success',
                    gatewayState.tone === 'warning' && 'text-warning',
                    gatewayState.tone === 'danger' && 'text-destructive',
                  )}
                >
                  {gatewayState.label}
                </span>
              </p>
              <p className="text-[0.72rem] leading-snug text-text-secondary">
                <span className="text-text-faint">Free heap: </span>
                <span className="tabular-nums">{heap(status?.free_heap)}</span>
              </p>
              <p className="text-[0.72rem] leading-snug text-text-secondary">
                <span className="text-text-faint">Uptime: </span>
                <span className="tabular-nums">{uptime(status?.uptime_s)}</span>
              </p>
            </div>

            <SidebarActions collapsed={collapsed} authed={authed} onLock={lock} />

            {/* auth row */}
            <div
              className={cn(
                'flex shrink-0 items-center justify-between gap-2 border-t border-border px-3 py-2',
                collapsed && 'lg:hidden',
              )}
            >
              <div className="min-w-0">
                <p className="truncate text-[0.72rem] font-medium text-midground">Local Operator</p>
                <p className="truncate text-[0.65rem] text-text-faint">
                  via {authed ? 'token' : 'locked'}
                </p>
              </div>
              {authed ? (
                <button
                  type="button"
                  onClick={lock}
                  title="Lock dashboard"
                  aria-label="Lock dashboard"
                  className="text-text-tertiary hover:text-midground"
                >
                  <Lock className="h-3.5 w-3.5" />
                </button>
              ) : (
                <Unlock className="h-3.5 w-3.5 text-warning" />
              )}
            </div>

            {/* footer */}
            <div
              className={cn(
                'flex shrink-0 items-center justify-between gap-2 border-t border-border px-3 py-2',
                collapsed && 'lg:hidden',
              )}
            >
              <span className="font-mono-ui text-[0.68rem] tabular-nums tracking-[0.08em] text-text-tertiary lowercase">
                {status?.version ? `v${status.version}` : 'v2.0.0'}
              </span>
              <a
                href="https://hermes-agent.nousresearch.com"
                target="_blank"
                rel="noopener noreferrer"
                className="label-display text-[0.68rem] tracking-[0.12em] text-midground hover:opacity-90"
              >
                Nous Research
              </a>
            </div>
          </aside>

          {/* ---------- main ---------- */}
          <div className="relative z-[2] flex min-h-0 min-w-0 flex-1 flex-col px-3 sm:px-5">
            {children}
          </div>
        </div>
      </div>

      {/* collapsed rail icons for the bottom blocks */}
      {collapsed && (
        <div className="pointer-events-none fixed bottom-2 left-0 z-50 hidden w-14 lg:block">
          <div className="pointer-events-auto flex flex-col items-center gap-2">
            <button
              type="button"
              onClick={onLockProxy(authed, lock)}
              aria-label="Lock dashboard"
              className="p-1 text-text-tertiary hover:text-midground"
            >
              <Lock className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function onLockProxy(authed: boolean, lock: () => void) {
  return () => {
    if (authed) lock()
  }
}

function SidebarNavLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  onNavigate: () => void
}) {
  const Icon = item.icon
  return (
    <li>
      <NavLink
        to={item.path}
        end={item.path === '/'}
        onClick={onNavigate}
        title={collapsed ? item.label : undefined}
        className={({ isActive }) =>
          cn(
            'group/nav relative flex items-center gap-3 px-5 py-2.5',
            'label-display text-[0.85rem] tracking-[0.12em] whitespace-nowrap transition-colors',
            'focus-visible:outline-none',
            isActive ? 'text-midground' : 'text-text-secondary hover:text-midground',
          )
        }
      >
        {({ isActive }) => (
          <>
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span
              className={cn(
                'truncate transition-opacity duration-300',
                collapsed ? 'lg:opacity-0' : 'lg:opacity-100',
              )}
            >
              {item.label}
            </span>
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 transition-opacity duration-200 group-hover/nav:opacity-5"
            />
            {isActive && (
              <span aria-hidden className="absolute bottom-0 left-0 top-0 w-px bg-midground" />
            )}
          </>
        )}
      </NavLink>
    </li>
  )
}

function SidebarActions({
  collapsed,
  authed,
  onLock,
}: {
  collapsed: boolean
  authed: boolean
  onLock: () => void
}) {
  const { push } = useToast()
  const [busy, setBusy] = useState(false)
  const { refreshStatus } = useAppData()

  const restart = async () => {
    setBusy(true)
    try {
      await api.post('/api/reboot')
      push('info', 'Rebooting the agent…')
      setTimeout(() => void refreshStatus(), 4000)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Reboot failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn('flex flex-col border-t border-border px-1 py-1.5', collapsed && 'lg:hidden')}>
      <button
        type="button"
        onClick={() => void restart()}
        disabled={busy}
        className="flex items-center gap-3 px-4 py-2 text-left text-[0.72rem] text-text-secondary transition-colors hover:text-midground disabled:opacity-50"
      >
        <RotateCw className={cn('h-3.5 w-3.5 shrink-0', busy && 'animate-spin')} />
        <span className="truncate">{busy ? 'Restarting…' : 'Restart Agent'}</span>
      </button>
      <button
        type="button"
        onClick={onLock}
        disabled={!authed}
        className="flex items-center gap-3 px-4 py-2 text-left text-[0.72rem] text-text-secondary transition-colors hover:text-midground disabled:opacity-40"
      >
        <Power className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">Lock Dashboard</span>
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Page header — the "SESSIONS" bar at the top of every route          */
/* ------------------------------------------------------------------ */

export function PageHeader({
  title,
  icon,
  actions,
  subtitle,
}: {
  title: string
  icon?: ReactNode
  actions?: ReactNode
  subtitle?: ReactNode
}) {
  return (
    <div className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border py-2">
      <div className="flex min-w-0 items-center gap-2">
        {icon && <span className="text-text-secondary">{icon}</span>}
        <h1 className="truncate label-display text-[0.9rem] font-bold tracking-[0.07em] text-midground">
          {title}
        </h1>
        {subtitle && <div className="min-w-0 truncate text-[0.72rem] text-text-faint">{subtitle}</div>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-1.5">{actions}</div>}
    </div>
  )
}

export function PageBody({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-[calc(2rem+env(safe-area-inset-bottom,0px))] pt-3">
      {children}
    </div>
  )
}

export function StatusChip() {
  const { status, online, authed } = useAppData()
  if (!online) return <Chip tone="danger" dot>offline</Chip>
  if (!authed) return <Chip tone="warning" dot>locked</Chip>
  return (
    <Chip tone="success" dot>
      {status?.wifi_connected === false ? 'no wifi' : 'live'}
    </Chip>
  )
}

export function useNavTo() {
  const navigate = useNavigate()
  return (path: string) => navigate(path)
}

export function NavButton({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Button variant="ghost" onClick={() => (window.location.href = to)}>
      {children}
    </Button>
  )
}
