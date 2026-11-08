import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent as ReactDragEvent } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowUp,
  Download,
  File,
  FileCode2,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  RefreshCw,
  Save,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { api } from '@/lib/api'
import { bytes, cn } from '@/lib/utils'
import { Button, Chip, Field, Modal, useConfirm, useToast } from '@/components/ui'

interface FsEntry {
  name: string
  path: string
  is_dir: boolean
  size?: number
  mtime?: number
}

interface FsList {
  path: string
  parent: string | null
  count: number
  entries: FsEntry[]
  error?: string
}

interface FsContent {
  path: string
  size: number
  content: string
  truncated?: boolean
  error?: string
}

const TEXT_EXT = /\.(py|txt|md|json|jsonl|html|htm|css|js|ts|tsx|svg|ini|cfg|conf|log|ya?ml|toml|csv)$/i

/* The reference Hermes Files page formats absolute timestamps, not relative
   ones. MicroPython's `time.time()` counts from 2000-01-01, so shift it. */
const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

function epochMs(mtime: number | undefined | null): number | null {
  if (!mtime) return null
  const seconds = mtime < 1_000_000_000 ? mtime + 946_684_800 : mtime
  // Files written before the RTC was ever set carry a 2000-era stamp.
  if (seconds < 978_307_200) return null
  return seconds * 1000
}

function formatTime(mtime: number | undefined | null): string {
  const ms = epochMs(mtime)
  return ms ? DATE_FORMAT.format(ms) : '-'
}

function formatBytes(size: number | undefined | null): string {
  if (size === undefined || size === null || Number.isNaN(size)) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function transferHasFiles(event: ReactDragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes('Files')
}

type SortKey = 'name' | 'size' | 'mtime'
type SortDir = 'asc' | 'desc'

function SortHeader({
  label,
  column,
  sort,
  dir,
  onSort,
}: {
  label: string
  column: SortKey
  sort: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
}) {
  const active = sort === column
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      aria-label={`Sort by ${label.toLowerCase()}`}
      title={`Sort by ${label.toLowerCase()}`}
      className={cn(
        'inline-flex items-center gap-1 text-left uppercase transition-colors',
        active ? 'text-midground' : 'text-text-tertiary hover:text-midground',
      )}
    >
      {label}
      <span aria-hidden className={cn('text-[0.8em]', !active && 'invisible')}>
        {dir === 'asc' ? '↑' : '↓'}
      </span>
    </button>
  )
}

export function FilesPage() {
  const { push } = useToast()
  const { confirm, confirmNode } = useConfirm()
  const fileInput = useRef<HTMLInputElement | null>(null)
  const dragDepth = useRef(0)

  const [path, setPath] = useState('')
  const [listing, setListing] = useState<FsList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [draggingFiles, setDraggingFiles] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [folderName, setFolderName] = useState('')
  const [creating, setCreating] = useState(false)

  const [editor, setEditor] = useState<{ path: string; content: string; size: number } | null>(null)
  const [editorBusy, setEditorBusy] = useState(false)

  const [sort, setSort] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const load = useCallback(async (target: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<FsList>('/api/files', target ? { path: target } : undefined)
      if (data.error) throw new Error(data.error)
      setListing(data)
      setPath(data.path === '/' ? '' : data.path.replace(/^\//, ''))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load('')
  }, [load])

  const activePath = listing?.path ?? '/'
  const canUpload = Boolean(listing) && !uploading

  const entries = useMemo(() => {
    const list = listing?.entries ?? []
    return [...list].sort((a, b) => {
      // Folders stay grouped above files, as in Explorer / Finder.
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
      let cmp: number
      if (sort === 'size') cmp = (a.size || 0) - (b.size || 0)
      else if (sort === 'mtime') cmp = (a.mtime || 0) - (b.mtime || 0)
      else cmp = a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [listing, sort, sortDir])

  const onSort = (key: SortKey) => {
    if (key === sort) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(key)
      setSortDir('asc')
    }
  }

  const openEntry = async (entry: FsEntry) => {
    if (entry.is_dir) {
      void load(entry.path)
      return
    }
    if (!TEXT_EXT.test(entry.name)) {
      download(entry)
      return
    }
    setEditorBusy(true)
    try {
      const data = await api.get<FsContent>('/api/files/content', { path: entry.path })
      if (data.error) throw new Error(data.error)
      setEditor({ path: data.path, content: data.content, size: data.size })
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Read failed')
    } finally {
      setEditorBusy(false)
    }
  }

  const download = (entry: FsEntry) => {
    if (entry.is_dir) return
    const token = localStorage.getItem('esp32_token') || ''
    const url = `/api/files/download?path=${encodeURIComponent(entry.path)}${
      token ? `&token=${encodeURIComponent(token)}` : ''
    }`
    const a = document.createElement('a')
    a.href = url
    a.download = entry.name
    a.click()
  }

  const save = async () => {
    if (!editor) return
    setEditorBusy(true)
    try {
      const res = await api.post<{ ok?: boolean; size?: number; error?: string }>('/api/files/save', {
        path: editor.path,
        content: editor.content,
      })
      if (res.error) throw new Error(res.error)
      push('ok', `Saved ${editor.path} (${bytes(res.size)})`)
      setEditor((prev) => (prev ? { ...prev, size: res.size || prev.size } : prev))
      void load(path)
    } catch (err) {
      push('err', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setEditorBusy(false)
    }
  }

  const createFolder = async () => {
    const name = folderName.trim()
    if (!name) {
      push('err', 'Folder name required')
      return
    }
    setCreating(true)
    try {
      const target = path ? `/${path}/${name}` : `/${name}`
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/files/mkdir', { path: target })
      if (res.error) throw new Error(res.error)
      push('ok', 'Folder created')
      setCreateOpen(false)
      setFolderName('')
      void load(path)
    } catch (err) {
      push('err', `Create failed: ${err instanceof Error ? err.message : 'unknown error'}`)
    } finally {
      setCreating(false)
    }
  }

  const remove = async (entry: FsEntry) => {
    const ok = await confirm(
      `Delete ${entry.name}?`,
      entry.is_dir
        ? 'This removes the folder and everything inside it.'
        : 'This removes the file.',
    )
    if (!ok) return
    try {
      const res = await api.post<{ ok?: boolean; error?: string }>('/api/files/delete', {
        path: entry.path,
      })
      if (res.error) throw new Error(res.error)
      push('ok', 'Deleted')
      void load(path)
    } catch (err) {
      push('err', `Delete failed: ${err instanceof Error ? err.message : 'unknown error'}`)
    }
  }

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const text = await file.text()
        const target = path ? `/${path}/${file.name}` : `/${file.name}`
        const res = await api.post<{ ok?: boolean; error?: string }>('/api/files/save', {
          path: target,
          content: text,
        })
        if (res.error) throw new Error(res.error)
      }
      push('ok', `${files.length} file${files.length === 1 ? '' : 's'} uploaded`)
      await load(path)
    } catch (err) {
      push('err', `Upload failed: ${err instanceof Error ? err.message : 'unknown error'}`)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const handleDragEnter = (event: ReactDragEvent<HTMLElement>) => {
    if (!canUpload || !transferHasFiles(event)) return
    event.preventDefault()
    dragDepth.current += 1
    setDraggingFiles(true)
  }

  const handleDragOver = (event: ReactDragEvent<HTMLElement>) => {
    if (!canUpload || !transferHasFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  const handleDragLeave = (event: ReactDragEvent<HTMLElement>) => {
    if (!canUpload || !transferHasFiles(event)) return
    event.preventDefault()
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDraggingFiles(false)
  }

  const handleDrop = (event: ReactDragEvent<HTMLElement>) => {
    if (!canUpload) return
    event.preventDefault()
    dragDepth.current = 0
    setDraggingFiles(false)
    void upload(event.dataTransfer.files)
  }

  return (
    <>
      {/* page header — same shape as Hermes: title, path badge, refresh */}
      <header className="flex min-h-14 w-full shrink-0 items-center justify-between gap-2 border-b border-border py-2">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <h1 className="min-w-0 shrink truncate text-sm font-bold tracking-[0.08em] text-midground">
            Files
          </h1>
          <span
            className="inline-flex max-w-[22rem] min-w-0 items-center truncate border border-midground/30 px-2 py-1 font-mono-ui text-xs tracking-[0.12em] text-midground/80"
            title={activePath}
          >
            {activePath}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void load(path)}
          disabled={loading}
          aria-label="Refresh files"
          className="shrink-0 p-2 text-text-secondary transition-colors hover:bg-midground/10 hover:text-midground disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-[calc(2rem+env(safe-area-inset-bottom,0px))] pt-3">
        <div className="flex min-w-0 max-w-full flex-col gap-4">
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(event) => void upload(event.currentTarget.files)}
          />

          <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div
              className="min-w-0 truncate font-mono-ui text-sm text-text-secondary"
              title={activePath}
            >
              {activePath}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Button
                onClick={() => fileInput.current?.click()}
                disabled={!canUpload}
                className="uppercase"
              >
                {uploading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Upload className="h-3.5 w-3.5" />
                )}
                Upload
              </Button>
              <Button
                onClick={() => setCreateOpen(true)}
                disabled={!listing}
                className="uppercase"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                Create
              </Button>
            </div>
          </div>

          {/* drop zone — clickable, drag-and-drop, exactly like the reference */}
          <button
            type="button"
            onClick={() => canUpload && fileInput.current?.click()}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            disabled={!canUpload}
            aria-label="Upload files"
            className={cn(
              'flex min-h-20 w-full min-w-0 items-center justify-between gap-4 border border-dashed px-4 py-3 text-left transition',
              draggingFiles
                ? 'border-midground bg-midground/10 text-midground'
                : 'border-border bg-background-base/20 text-text-secondary hover:border-text-tertiary hover:bg-midground/5',
              'disabled:cursor-not-allowed disabled:opacity-60',
            )}
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-background-base/45 text-text-tertiary">
                {uploading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold uppercase tracking-[0.08em] text-midground">
                  {uploading ? 'Uploading' : draggingFiles ? 'Release to upload' : 'Drop files here'}
                </span>
                <span
                  className="block truncate font-mono-ui text-xs text-text-secondary"
                  title={activePath}
                >
                  {activePath}
                </span>
              </span>
            </span>
            <span className="hidden shrink-0 text-xs font-semibold uppercase tracking-[0.08em] text-text-tertiary sm:block">
              Choose files
            </span>
          </button>

          <section className="min-w-0 max-w-full overflow-hidden border border-border">
            {error && (
              <div className="border-b border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="overflow-x-auto">
              <div className="grid min-w-[42rem] grid-cols-[minmax(12rem,1fr)_7rem_10rem_5.5rem] items-center gap-3 border-b border-border px-4 py-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-tertiary">
                <SortHeader
                  label="Name"
                  column="name"
                  sort={sort}
                  dir={sortDir}
                  onSort={onSort}
                />
                <SortHeader
                  label="Size"
                  column="size"
                  sort={sort}
                  dir={sortDir}
                  onSort={onSort}
                />
                <SortHeader
                  label="Modified"
                  column="mtime"
                  sort={sort}
                  dir={sortDir}
                  onSort={onSort}
                />
                <span className="text-right">Actions</span>
              </div>

              {listing?.parent && (
                <button
                  type="button"
                  onClick={() => void load((listing.parent || '/').replace(/^\//, ''))}
                  className="grid w-full min-w-[42rem] grid-cols-[minmax(12rem,1fr)_7rem_10rem_5.5rem] items-center gap-3 border-b border-border/60 px-4 py-2 text-left text-sm transition hover:bg-midground/4"
                >
                  <span className="flex min-w-0 items-center gap-2 font-mono-ui text-text-secondary">
                    <ArrowUp className="h-4 w-4 shrink-0 text-text-tertiary" />
                    ..
                  </span>
                  <span />
                  <span />
                  <span />
                </button>
              )}

              {loading && !listing ? (
                <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-tertiary">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading files...
                </div>
              ) : entries.length === 0 ? (
                <div className="py-12 text-center text-sm text-text-tertiary">No files</div>
              ) : (
                entries.map((entry) => (
                  <div
                    key={entry.path}
                    className="grid min-w-[42rem] grid-cols-[minmax(12rem,1fr)_7rem_10rem_5.5rem] items-center gap-3 border-b border-border/60 px-4 py-2 text-sm last:border-b-0 hover:bg-midground/4"
                  >
                    <button
                      type="button"
                      onClick={() => void openEntry(entry)}
                      title={!entry.is_dir && TEXT_EXT.test(entry.name) ? 'Open in editor' : undefined}
                      className="flex min-w-0 items-center gap-2 text-left font-mono-ui text-midground"
                    >
                      {entry.is_dir ? (
                        <Folder className="h-4 w-4 shrink-0 text-warning" />
                      ) : (
                        <File className="h-4 w-4 shrink-0 text-text-tertiary" />
                      )}
                      <span className="truncate">{entry.name}</span>
                    </button>
                    <span className="text-xs tabular-nums text-text-secondary">
                      {entry.is_dir ? '-' : formatBytes(entry.size)}
                    </span>
                    <span className="truncate text-xs text-text-secondary">
                      {formatTime(entry.mtime)}
                    </span>
                    <span className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => void openEntry(entry)}
                        aria-label={
                          entry.is_dir ? `Open ${entry.name}` : `Download ${entry.name}`
                        }
                        title={entry.is_dir ? 'Open' : 'Download'}
                        className="p-1 text-text-tertiary transition-colors hover:text-midground"
                      >
                        {entry.is_dir ? (
                          <FolderOpen className="h-3.5 w-3.5" />
                        ) : (
                          <Download className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(entry)}
                        aria-label={`Delete ${entry.name}`}
                        title="Delete"
                        className="p-1 text-text-tertiary transition-colors hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      </div>

      {/* editor — micro-only affordance, opened from a file's name.
          Portaled to <body> so the shell's stacking context cannot put the
          sidebar above it. */}
      {editor &&
        createPortal(
          <div className="fixed inset-0 z-[70] flex flex-col bg-background-base animate-fade-in">
            <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <FileCode2 className="h-4 w-4 text-text-secondary" />
                <span className="truncate font-mono-ui text-[0.8rem] text-midground">
                  {editor.path}
                </span>
                <Chip tone="muted">{bytes(editor.content.length)}</Chip>
              </div>
              <div className="flex items-center gap-1.5">
                <Button variant="ghost" onClick={() => void load(path)}>
                  <RefreshCw className="h-3 w-3" /> Reload list
                </Button>
                <Button variant="primary" loading={editorBusy} onClick={() => void save()}>
                  <Save className="h-3 w-3" /> Save
                </Button>
                <Button variant="ghost" onClick={() => setEditor(null)}>
                  <X className="h-3 w-3" /> Close
                </Button>
              </div>
            </div>
            <textarea
              value={editor.content}
              onChange={(e) =>
                setEditor((prev) => (prev ? { ...prev, content: e.target.value } : prev))
              }
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                  e.preventDefault()
                  void save()
                }
              }}
              spellCheck={false}
              className="min-h-0 flex-1 resize-none bg-transparent px-3 py-3 font-mono-ui text-[0.78rem] leading-relaxed text-midground outline-none"
            />
          </div>,
          document.body,
        )}

      <Modal
        open={createOpen}
        title="Create folder"
        onClose={() => {
          if (creating) return
          setCreateOpen(false)
          setFolderName('')
        }}
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setCreateOpen(false)
                setFolderName('')
              }}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button variant="primary" loading={creating} onClick={() => void createFolder()}>
              <FolderPlus className="h-3 w-3" /> Create
            </Button>
          </>
        }
      >
        <p className="mb-3 text-[0.8rem] text-text-secondary">
          Target: <span className="font-mono-ui text-midground">{activePath}</span>
        </p>
        <Field label="Folder name">
          <input
            className="input"
            autoFocus
            placeholder="Folder name"
            value={folderName}
            onChange={(e) => setFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void createFolder()
            }}
            disabled={creating}
          />
        </Field>
      </Modal>

      {confirmNode}
    </>
  )
}
