import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { Check, FolderOpen, Loader2, Plus, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'

export function OutputFolderSelector() {
  const { t } = useUiTranslation('navigation')
  const workspaces = useStore(s => s.workspaces)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const browsingUploads = useStore(s => s.browsingUploads)
  const switchWorkspace = useStore(s => s.switchWorkspace)
  const createWorkspace = useStore(s => s.createWorkspace)
  const deleteWorkspace = useStore(s => s.deleteWorkspace)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const handleDelete = async (name: string, event: MouseEvent) => {
    event.stopPropagation()
    if (confirmDelete !== name) {
      setConfirmDelete(name)
      setTimeout(() => setConfirmDelete(current => (current === name ? null : current)), 4000)
      return
    }
    setConfirmDelete(null)
    setDeleting(name)
    setDeleteError(null)
    try {
      await deleteWorkspace(name)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : String(error))
      setTimeout(() => setDeleteError(null), 6000)
    } finally {
      setDeleting(null)
    }
  }

  useEffect(() => {
    if (!open) return
    const handler = (event: globalThis.MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false)
        setCreating(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleCreate = async () => {
    const name = newName.trim().replace(/\s+/g, '-')
    if (!name) return
    try {
      await createWorkspace(name)
      setNewName('')
      setCreating(false)
      setOpen(false)
    } catch {
      // The store publishes the actionable error.
    }
  }

  return (
    <div className="relative shrink-0" ref={dropdownRef}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary" title={t('outputFolder.switch')} aria-label={`${t('outputFolder.switch')}: ${browsingUploads ? t('outputFolder.uploads') : activeWorkspace}`}>
        <FolderOpen size={12} />
        <span className="max-w-[150px] truncate">{t('outputFolder.option')} · {browsingUploads ? t('outputFolder.uploads') : activeWorkspace}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-bg-secondary shadow-lg">
          <div className="border-b border-border px-2 py-1.5"><span className="text-[10px] uppercase tracking-wider text-text-muted">{t('outputFolder.list')}</span></div>
          <div className="max-h-[200px] overflow-y-auto">
            {workspaces.map(workspace => (
              <div key={workspace.name} className="group flex items-center transition-colors hover:bg-bg-hover">
                <button onClick={() => { switchWorkspace(workspace.name); setOpen(false) }} className={`flex min-w-0 flex-1 items-center justify-between px-3 py-2 text-left text-xs ${workspace.name === activeWorkspace && !browsingUploads ? 'text-accent-blue' : 'text-text-secondary'}`}>
                  <span className="truncate">{workspace.name}</span>
                  {workspace.name === activeWorkspace && !browsingUploads && <Check size={12} className="shrink-0" />}
                </button>
                {workspace.name !== 'default' && (
                  <button onClick={event => handleDelete(workspace.name, event)} disabled={deleting === workspace.name} className={`shrink-0 px-2 py-2 transition-colors ${confirmDelete === workspace.name ? 'bg-red-500/15 text-red-400' : deleting === workspace.name ? 'cursor-wait text-text-muted' : 'text-text-muted opacity-0 hover:text-red-400 focus-visible:opacity-100 group-hover:opacity-100'}`} title={confirmDelete === workspace.name ? `Click again to permanently delete "${workspace.name}" and its ${workspace.file_count ?? 0} files` : `Delete output folder (${workspace.file_count ?? 0} files)`}>
                    {deleting === workspace.name ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                )}
              </div>
            ))}
          </div>
          {deleteError && <div className="border-t border-border px-3 py-1.5 text-[10px] leading-snug text-red-400">{deleteError}</div>}
          <div className="border-t border-border">
            <button onClick={() => { switchWorkspace('__uploads__'); setOpen(false) }} className={`flex w-full items-center justify-between px-3 py-2 text-left text-xs transition-colors hover:bg-bg-hover ${browsingUploads ? 'text-accent-blue' : 'text-text-secondary'}`} title="Browse uploaded media">
              <span className="flex items-center gap-1.5"><Upload size={12} /> {t('outputFolder.uploads')}</span>
              {browsingUploads && <Check size={12} />}
            </button>
          </div>
          <div className="border-t border-border p-2">
            {creating ? (
              <div className="flex gap-1.5">
                <input type="text" value={newName} onChange={event => setNewName(event.target.value)} onKeyDown={event => event.key === 'Enter' && void handleCreate()} placeholder="output-folder" className="flex-1 rounded border border-border bg-bg-tertiary px-2 py-1 text-xs text-text-primary focus:border-accent-blue focus:outline-none" autoFocus />
                <button onClick={() => void handleCreate()} disabled={!newName.trim()} className="rounded bg-accent-blue px-2 py-1 text-xs text-white hover:bg-accent-blue-hover disabled:opacity-50">Create</button>
              </div>
            ) : (
              <button onClick={() => setCreating(true)} className="flex w-full items-center gap-1 px-1 py-1 text-left text-xs text-accent-blue hover:text-accent-blue-hover"><Plus size={12} /> New output folder</button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
