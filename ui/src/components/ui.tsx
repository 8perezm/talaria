import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import { X, Loader2, AlertTriangle, CheckCircle2, Info } from 'lucide-react'

/* ------------------------------------------------------------------ */
/* Button                                                              */
/* ------------------------------------------------------------------ */

type ButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'

export function Button({
  children,
  onClick,
  variant = 'default',
  size = 'md',
  disabled,
  loading,
  type = 'button',
  title,
  className,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  disabled?: boolean
  loading?: boolean
  type?: 'button' | 'submit'
  title?: string
  className?: string
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        'btn',
        variant === 'primary' && 'btn-primary',
        variant === 'danger' && 'btn-danger',
        variant === 'ghost' && 'btn-ghost',
        size === 'sm' && 'btn-sm',
        className,
      )}
    >
      {loading && <Loader2 className="h-3 w-3 animate-spin" />}
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Panel                                                               */
/* ------------------------------------------------------------------ */

export function Panel({
  title,
  icon,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cn('panel min-w-0', className)}>
      {title !== undefined && (
        <header className="panel-head">
          {icon && <span className="shrink-0 text-text-secondary">{icon}</span>}
          <div className="min-w-0 flex-1 label-display text-[0.95rem] tracking-[0.02em]">{title}</div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Chip                                                                */
/* ------------------------------------------------------------------ */

export function Chip({
  children,
  tone = 'default',
  dot,
  className,
}: {
  children: ReactNode
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'muted'
  dot?: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        'chip',
        tone === 'success' && 'text-success',
        tone === 'warning' && 'text-warning',
        tone === 'danger' && 'text-destructive',
        tone === 'muted' && 'text-text-tertiary',
        className,
      )}
    >
      {dot && <span className="dot" />}
      {children}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/* Field                                                               */
/* ------------------------------------------------------------------ */

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="min-w-0">
      <span className="field-label">{label}</span>
      {children}
      {hint && <p className="mt-1 text-[0.72rem] leading-snug text-text-faint">{hint}</p>}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-[16px] w-[30px] shrink-0 items-center border transition-colors duration-150',
        checked ? 'border-midground' : 'border-border hover:border-midground/50',
      )}
    >
      <span
        className={cn(
          'absolute top-[2px] h-[10px] w-[10px] transition-[left,background-color] duration-150',
          checked ? 'left-[16px] bg-midground' : 'left-[2px] bg-text-faint',
        )}
      />
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Empty / Loading                                                     */
/* ------------------------------------------------------------------ */

export function EmptyState({
  icon,
  title,
  detail,
  action,
}: {
  icon?: ReactNode
  title: string
  detail?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-text-faint">{icon}</div>}
      <p className="label-display text-[0.72rem] tracking-[0.16em] text-text-secondary">{title}</p>
      {detail && <p className="max-w-md text-[0.8rem] leading-relaxed text-text-faint">{detail}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading.' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-[0.8rem] text-text-tertiary">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorNote({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-2 border border-destructive/60 px-3 py-2 text-[0.8rem] text-destructive">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0 flex-1 break-words">{children}</div>
      {onRetry && (
        <button type="button" onClick={onRetry} className="underline underline-offset-2">
          retry
        </button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Modal (no native dialogs anywhere in this app)                      */
/* ------------------------------------------------------------------ */

export function Modal({
  open,
  title,
  children,
  onClose,
  footer,
  wide,
}: {
  open: boolean
  title: string
  children: ReactNode
  onClose: () => void
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  /* Portal to <body>: pages live inside the shell's stacking context, where
     z-[80] cannot rise above the sidebar and the backdrop stops at the main
     column. */
  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-start justify-center overflow-y-auto bg-black/75 p-4 pt-[10vh] animate-fade-in">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'w-full border border-border bg-background-base shadow-[0_24px_80px_rgba(0,0,0,0.6)] animate-dialog-in',
          wide ? 'max-w-3xl' : 'max-w-lg',
        )}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="label-display text-[0.72rem] tracking-[0.16em] text-midground">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-text-tertiary hover:text-midground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-4 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

/** Promise-based confirmation, replacing native confirm(). */
export function useConfirm() {
  const [state, setState] = useState<{
    title: string
    message: ReactNode
    resolve: (ok: boolean) => void
  } | null>(null)

  const confirm = useCallback(
    (title: string, message: ReactNode) =>
      new Promise<boolean>((resolve) => setState({ title, message, resolve })),
    [],
  )

  const node = (
    <Modal
      open={state !== null}
      title={state?.title ?? ''}
      onClose={() => {
        state?.resolve(false)
        setState(null)
      }}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={() => {
              state?.resolve(false)
              setState(null)
            }}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              state?.resolve(true)
              setState(null)
            }}
          >
            Confirm
          </Button>
        </>
      }
    >
      <div className="text-[0.85rem] leading-relaxed text-text-secondary">{state?.message}</div>
    </Modal>
  )

  return { confirm, confirmNode: node }
}

/* ------------------------------------------------------------------ */
/* Toast                                                               */
/* ------------------------------------------------------------------ */

type Toast = { id: number; tone: 'ok' | 'err' | 'info'; text: string }
type ToastContextValue = { push: (tone: Toast['tone'], text: string) => void }

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast outside provider')
  return ctx
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)

  const push = useCallback((tone: Toast['tone'], text: string) => {
    const id = ++seq.current
    setItems((prev) => [...prev.slice(-4), { id, tone, text }])
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 4200)
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[90] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              'pointer-events-auto flex items-start gap-2 border px-3 py-2 text-[0.78rem] leading-snug animate-toast-in',
              'bg-background-base',
              t.tone === 'ok' && 'border-success/60 text-success',
              t.tone === 'err' && 'border-destructive/60 text-destructive',
              t.tone === 'info' && 'border-border text-text-secondary',
            )}
          >
            {t.tone === 'ok' && <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
            {t.tone === 'err' && <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
            {t.tone === 'info' && <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
            <span className="min-w-0 break-words">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

/* ------------------------------------------------------------------ */
/* Tabs (segmented control, exactly the upstream look)                 */
/* ------------------------------------------------------------------ */

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: Array<{ id: T; label: ReactNode; badge?: number }>
  value: T
  onChange: (id: T) => void
  className?: string
}) {
  return (
    <div role="tablist" className={cn('flex items-stretch border border-border', className)}>
      {tabs.map((tab) => {
        const active = tab.id === value
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 label-display text-[0.7rem] transition-colors',
              'border-r border-border last:border-r-0',
              active
                ? 'bg-midground text-background-base'
                : 'text-text-secondary hover:bg-midground/8 hover:text-midground',
            )}
          >
            {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span
                className={cn(
                  'tabular-nums text-[0.6rem]',
                  active ? 'text-background-base/70' : 'text-text-faint',
                )}
              >
                {tab.badge}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Stat strip (the bordered counters row under every page header)      */
/* ------------------------------------------------------------------ */

export function StatStrip({
  items,
}: {
  items: Array<{ label: string; value: ReactNode; tone?: 'default' | 'success' | 'warning' | 'danger' }>
}) {
  return (
    <div className="flex flex-wrap items-stretch divide-x divide-border border border-border">
      {items.map((item) => (
        <div key={item.label} className="min-w-[6.5rem] flex-1 px-3.5 py-2">
          <div
            className={cn(
              'text-[1.05rem] font-semibold leading-tight tabular-nums',
              item.tone === 'success' && 'text-success',
              item.tone === 'warning' && 'text-warning',
              item.tone === 'danger' && 'text-destructive',
              (!item.tone || item.tone === 'default') && 'text-midground',
            )}
          >
            {item.value}
          </div>
          <div className="mt-0.5 label-display text-[0.6rem] tracking-[0.14em] text-text-tertiary">
            {item.label}
          </div>
        </div>
      ))}
    </div>
  )
}
