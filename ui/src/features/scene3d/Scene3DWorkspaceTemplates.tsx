import { useEffect, useState } from 'react'
import { Bot, Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import {
  getWorld3DWorkspaceTemplate, listWorld3DWorkspaceTemplates, type World3DWorkspaceTemplate,
} from '../../api/world3dWorkspace'
import { parseScene3DDocument } from './document.ts'
import { packFromWorkspace } from './templateLibraryModel'
import type { World3DUserTemplate } from './userTemplates.ts'

function TemplateCard({ item, selected, disabled, onPick }: {
  item: World3DWorkspaceTemplate; selected: boolean; disabled: boolean; onPick: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const changed = item.updatedAt ? formatAppTimestamp(Date.parse(item.updatedAt) / 1000) : ''
  const facts = [
    t('workspaceTemplates.objects', { count: item.slots }),
    item.pending ? t('workspaceTemplates.pending', { count: item.pending }) : '',
    item.duration ? `${item.duration}s` : '',
    changed,
  ].filter(Boolean).join(' · ')
  return <button type="button" disabled={disabled} aria-pressed={selected} data-testid={`world3d-workspace-template-${item.id}`} onClick={onPick}
    className={`block w-full rounded-lg border p-3 text-left disabled:opacity-40 ${selected ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary hover:bg-bg-hover'}`}>
    <span className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
      {item.createdBy === 'agent' || item.createdBy === 'wizard'
        ? <span className="inline-flex items-center gap-0.5 rounded border border-fuchsia-400/40 bg-fuchsia-400/10 px-1 text-[10px] font-medium text-fuchsia-200">
          <Bot size={10} aria-hidden="true" /> {t(`workspaceTemplates.by.${item.createdBy}`)}
        </span>
        : null}
      {item.title}
    </span>
    <span className="mt-1 block text-xs leading-5 text-text-secondary">{item.description || t('userTemplates.noDescription')}</span>
    <span className="mt-1 block text-[11px] text-text-muted">{facts}</span>
    <span className="mt-0.5 block font-mono text-[10px] text-text-muted">{item.id}</span>
  </button>
}

/**
 * Personal Video 3D templates stored in the workspace. Agents create them with
 * ``world3d.templates.user.put``; they are listed here so the user can open,
 * change and reuse them like the ones they saved themselves.
 */
export function Scene3DWorkspaceTemplates({ workspace, disabled, selectedId, onApply }: {
  workspace?: string
  disabled: boolean
  selectedId?: string
  onApply: (pack: World3DUserTemplate) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  // Keyed by workspace: switching workspaces shows the loader, never the previous workspace's list.
  const [loaded, setLoaded] = useState<{ workspace: string; templates: World3DWorkspaceTemplate[] } | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!workspace) return
    const controller = new AbortController()
    listWorld3DWorkspaceTemplates(workspace, controller.signal)
      .then(templates => setLoaded({ workspace, templates }))
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)) })
    return () => controller.abort()
  }, [workspace])
  const templates = loaded && loaded.workspace === workspace ? loaded.templates : null
  if (!workspace || (templates !== null && templates.length === 0 && !error)) return null
  const pick = (item: World3DWorkspaceTemplate) => {
    setBusy(item.id); setError('')
    getWorld3DWorkspaceTemplate(workspace, item.id)
      .then(stored => {
        const document = parseScene3DDocument(stored.document)
        if (!document) throw new Error(t('workspaceTemplates.invalid'))
        onApply(packFromWorkspace(item, document))
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(''))
  }
  return <section className="mb-3 px-1" aria-label={t('workspaceTemplates.title')} data-testid="world3d-workspace-templates">
    <h3 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
      {t('workspaceTemplates.title')} <span className="text-text-muted">{templates?.length ?? ''}</span>
      {busy || templates === null ? <Loader2 size={14} className="animate-spin text-text-muted" /> : null}
    </h3>
    <p className="mt-1 text-xs leading-5 text-text-secondary">{t('workspaceTemplates.help')}</p>
    {error ? <p role="alert" className="mt-2 text-xs text-red-300">{error}</p> : null}
    <div className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2">
      {(templates ?? []).map(item => <TemplateCard key={item.id} item={item} selected={selectedId === item.id}
        disabled={disabled || Boolean(busy)} onPick={() => pick(item)} />)}
    </div>
  </section>
}
