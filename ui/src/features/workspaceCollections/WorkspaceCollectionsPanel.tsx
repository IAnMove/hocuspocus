import { controlChoice } from '../../i18n/controlLabel'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { FolderKanban, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import {
  createWorkspaceCollection, deleteWorkspaceCollection, fetchAssets, fetchProductions,
  fetchProjects, fetchWorkspaceCollections, updateWorkspaceCollection,
  type AssetCatalogItem, type ProductionCatalogItem, type ProjectCatalogItem, type WorkspaceCollection,
} from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { useCollectionPresentation } from './collectionPresentation'
import { CollectionRecovery } from './CollectionRecovery'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40'

function toggle(items: string[], id: string): string[] {
  return items.includes(id) ? items.filter(item => item !== id) : [...items, id]
}

export function WorkspaceCollectionsPanel() {
  const { t } = useUiTranslation('navigation')
  const { t: tActivity } = useUiTranslation('activity')
  const { t: tWs } = useUiTranslation('workspaces')
  const { t: tCommon } = useUiTranslation('common')
  const [items, setItems] = useState<WorkspaceCollection[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState<WorkspaceCollection | null>(null)
  const [projects, setProjects] = useState<ProjectCatalogItem[]>([])
  const [assets, setAssets] = useState<AssetCatalogItem[]>([])
  const [productions, setProductions] = useState<ProductionCatalogItem[]>([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const selectedRef = useRef(selectedId)
  useLayoutEffect(() => { selectedRef.current = selectedId }, [selectedId])
  const loadSequence = useRef(0)
  const invalidateLoad = useCallback(() => { loadSequence.current += 1; setLoading(false) }, [])

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setLoading(true); setError('')
    try {
      const [workspaces, projectPage, assetPage, productionPage] = await Promise.all([
        fetchWorkspaceCollections(), fetchProjects({ limit: 500 }),
        fetchAssets({ limit: 500 }), fetchProductions({ limit: 500 }),
      ])
      if (sequence !== loadSequence.current) return
      setItems(workspaces.workspaces)
      setProjects(projectPage.projects)
      setAssets(assetPage.assets)
      setProductions(productionPage.productions)
      const selected = workspaces.workspaces.find(item => item.id === selectedRef.current) || workspaces.workspaces[0] || null
      setSelectedId(selected?.id || '')
      setDraft(selected)
    } catch (reason) {
      if (sequence === loadSequence.current) setError(reason instanceof Error ? reason.message : tWs('collections.loadFailed'))
    } finally { if (sequence === loadSequence.current) setLoading(false) }
  }, [tWs])

  useEffect(() => { void load(); return () => { loadSequence.current += 1 } }, [load])
  const openCollection = useCallback((collection: WorkspaceCollection) => {
    invalidateLoad()
    setItems(current => [collection, ...current.filter(item => item.id !== collection.id)])
    setSelectedId(collection.id)
    setDraft(collection)
    setError('')
  }, [invalidateLoad])
  useEffect(() => {
    const open = (event: Event) => {
      const collection = (event as CustomEvent<{ collection?: WorkspaceCollection }>).detail?.collection
      if (!collection?.id) return
      openCollection(collection)
    }
    window.addEventListener('hocuspocus:workspace-collection-open', open)
    return () => window.removeEventListener('hocuspocus:workspace-collection-open', open)
  }, [openCollection])

  const dirty = useMemo(() => {
    const original = items.find(item => item.id === draft?.id)
    return Boolean(draft && original && JSON.stringify(draft) !== JSON.stringify(original))
  }, [draft, items])
  const presentation = useCollectionPresentation({ draft, selectedId, newName, dirty, loading, saving,
    setDraft, setSelectedId, setNewName, setItems, setSaving, invalidateLoad })

  const select = (item: WorkspaceCollection) => { setSelectedId(item.id); setDraft(item); setError('') }
  const create = async () => {
    const name = newName.trim(); if (!name) return
    invalidateLoad()
    setSaving(true); setError('')
    try {
      const created = await createWorkspaceCollection({ name })
      setItems(current => [created, ...current]); setSelectedId(created.id); setDraft(created); setNewName('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }
  const save = async () => {
    if (!draft?.id) return
    invalidateLoad()
    setSaving(true); setError('')
    try {
      const changed = await updateWorkspaceCollection(draft)
      setItems(current => current.map(item => item.id === changed.id ? changed : item)); setDraft(changed)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }
  const remove = async () => {
    if (!draft || !window.confirm(tWs('collections.deleteConfirm', { name: draft.name }))) return
    setSaving(true); setError('')
    try {
      await deleteWorkspaceCollection(draft.id)
      const remaining = items.filter(item => item.id !== draft.id)
      setItems(remaining); setDraft(remaining[0] || null); setSelectedId(remaining[0]?.id || '')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }

  return (
    <section ref={presentation.rootRef} data-collection-ready={!loading ? 'true' : 'false'} data-wizard-anchor="workspace-collection" aria-label={tWs('collections.aria')} className="flex h-full min-h-0 overflow-hidden rounded-xl border border-border bg-bg-primary">
      <fieldset disabled={saving} className="flex min-w-0 flex-1">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-bg-secondary">
        <div className="border-b border-border p-3">
          <div className="flex items-center gap-2 text-sm font-semibold"><FolderKanban size={16} className="text-violet-300" /> {t('headings.workspaces')}</div>
          <p className="mt-1 text-[10px] text-text-muted">{tActivity('collectionsHint')}</p>
          <div className="mt-3 flex gap-1">
            <input aria-label={tWs('collections.newName')} value={newName} onChange={event => setNewName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void create() }} placeholder={tWs('collections.placeholder')} className="min-w-0 flex-1 rounded-md border border-border bg-bg-primary px-2 py-1.5 text-xs" />
            <button className={button} disabled={!newName.trim() || saving} onClick={() => void create()} title={tWs('collections.createTitle')} aria-label={tWs('collections.createTitle')}><Plus size={13} /></button>
          </div>
        </div>
        <nav aria-label={tWs('collections.savedAria')} className="min-h-0 flex-1 overflow-y-auto p-2">
          {items.map(item => <button key={item.id} onClick={() => select(item)} className={`mb-1 w-full rounded-lg border p-2 text-left ${item.id === selectedId ? 'border-violet-500/50 bg-violet-500/10' : 'border-transparent hover:bg-bg-hover'}`}>
            <div className="truncate text-xs font-medium text-text-primary">{item.name}</div>
            <div className="mt-1 text-[10px] text-text-muted">{[
              tActivity('projectCount', { count: item.project_ids.length }),
              tActivity('assetCount', { count: item.asset_ids.length }),
              tActivity('productionCount', { count: item.production_ids.length }),
            ].join(' · ')}</div>
          </button>)}
          {!items.length && !loading && <p className="p-3 text-xs text-text-muted">{tWs('collections.empty')}</p>}
        </nav>
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <CollectionRecovery onRecovered={openCollection} onBusyChange={setSaving} disabled={dirty} />
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="min-w-0"><h2 className="text-sm font-semibold text-text-primary">{draft?.name || tWs('collections.untitled')}</h2><p className="break-all text-[10px] text-text-muted">{draft?.id ? tWs('commands.identity', { id: draft.id, revision: draft.revision }) : tWs('collections.idsHint')}</p></div>
          <div className="flex gap-1"><button className={button} onClick={() => void load()} title={tCommon('actions.refresh')} aria-label={tCommon('actions.refresh')}><RefreshCw size={13} className={loading ? 'animate-spin' : ''} /></button>{draft && <><button className={button} disabled={!dirty || saving} onClick={() => void save()}><Save size={13} /> {tCommon('actions.save')}</button><button className={`${button} text-red-300`} disabled={saving} onClick={() => void remove()} title={controlChoice(saving, 'disabled.waitForSave', 'a11y.deleteCollection')} aria-label={controlChoice(saving, 'disabled.waitForSave', 'a11y.deleteCollection')}><Trash2 size={13} /></button></>}</div>
        </div>
        {error && <div role="alert" className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{error}</div>}
        {loading && !draft ? <div className="flex items-center justify-center gap-2 p-12 text-xs text-text-muted"><Loader2 size={15} className="animate-spin" /> {tCommon('status.loading')}</div> : draft ? <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2"><label className="text-[10px] text-text-muted">{tCommon('fields.name')}<input aria-label={tCommon('fields.name')} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} className="mt-1 block w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary" /></label><label className="text-[10px] text-text-muted">{tCommon('fields.description')}<input aria-label={tCommon('fields.description')} value={draft.description} onChange={event => setDraft({ ...draft, description: event.target.value })} className="mt-1 block w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary" /></label></div>
          <ReferenceGroup title={t('entities.project_other')} entries={projects.map(item => ({ id: item.id, label: item.title, hint: item.kind }))} selected={draft.project_ids} onToggle={id => setDraft({ ...draft, project_ids: toggle(draft.project_ids, id) })} />
          <ReferenceGroup title={t('entities.asset_other')} entries={assets.map(item => ({ id: item.id, label: item.filename, hint: item.kind }))} selected={draft.asset_ids} onToggle={id => setDraft({ ...draft, asset_ids: toggle(draft.asset_ids, id) })} />
          <ReferenceGroup title={t('entities.production_other')} entries={productions.map(item => ({ id: item.id, label: item.title, hint: item.kind }))} selected={draft.production_ids} onToggle={id => setDraft({ ...draft, production_ids: toggle(draft.production_ids, id) })} />
        </div> : null}
      </div>
      </fieldset>
    </section>
  )
}

function ReferenceGroup({ title, entries, selected, onToggle }: { title: string; entries: Array<{ id: string; label: string; hint: string }>; selected: string[]; onToggle: (id: string) => void }) {
  const { t } = useUiTranslation('workspaces')
  const listed = new Set(entries.map(entry => entry.id))
  // A selected exact ID may be outside the loaded catalog page. Keep it visible
  // and editable rather than presenting a count with hidden membership.
  entries = [...entries, ...selected.filter(id => !listed.has(id)).map(id => ({ id, label: id, hint: t('commands.referenceOutsidePage') }))]
  return <fieldset className="rounded-lg border border-border bg-bg-secondary p-3"><legend className="px-1 text-xs font-semibold text-text-primary">{title} <span className="text-text-muted">({selected.length})</span></legend><div className="mt-1 grid max-h-48 gap-1 overflow-y-auto md:grid-cols-2 xl:grid-cols-3">{entries.map(entry => <label key={entry.id} className="flex cursor-pointer items-start gap-2 rounded p-2 hover:bg-bg-hover"><input aria-label={entry.label} type="checkbox" checked={selected.includes(entry.id)} onChange={() => onToggle(entry.id)} /><span className="min-w-0"><span className="block truncate text-xs text-text-primary" title={entry.label}>{entry.label}</span><span className="text-[9px] text-text-muted">{entry.hint} · {entry.id}</span></span></label>)}{!entries.length && <p className="text-[10px] text-text-muted">{t('collections.emptyType')}</p>}</div></fieldset>
}

export default WorkspaceCollectionsPanel
