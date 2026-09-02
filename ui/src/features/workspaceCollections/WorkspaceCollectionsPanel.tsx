import { useCallback, useEffect, useMemo, useState } from 'react'
import { FolderKanban, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import {
  createWorkspaceCollection, deleteWorkspaceCollection, fetchAssets, fetchProductions,
  fetchProjects, fetchWorkspaceCollections, updateWorkspaceCollection,
  type AssetCatalogItem, type ProductionCatalogItem, type ProjectCatalogItem, type WorkspaceCollection,
} from '../../api/client'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40'

function toggle(items: string[], id: string): string[] {
  return items.includes(id) ? items.filter(item => item !== id) : [...items, id]
}

export function WorkspaceCollectionsPanel() {
  const [items, setItems] = useState<WorkspaceCollection[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState<WorkspaceCollection | null>(null)
  const [projects, setProjects] = useState<ProjectCatalogItem[]>([])
  const [assets, setAssets] = useState<AssetCatalogItem[]>([])
  const [productions, setProductions] = useState<ProductionCatalogItem[]>([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [workspaces, projectPage, assetPage, productionPage] = await Promise.all([
        fetchWorkspaceCollections(), fetchProjects({ limit: 500 }),
        fetchAssets({ limit: 500 }), fetchProductions({ limit: 500 }),
      ])
      setItems(workspaces.workspaces)
      setProjects(projectPage.projects)
      setAssets(assetPage.assets)
      setProductions(productionPage.productions)
      const selected = workspaces.workspaces.find(item => item.id === selectedId) || workspaces.workspaces[0] || null
      setSelectedId(selected?.id || '')
      setDraft(selected)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudieron cargar los Workspaces')
    } finally { setLoading(false) }
  }, [selectedId])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const open = (event: Event) => {
      const collection = (event as CustomEvent<{ collection?: WorkspaceCollection }>).detail?.collection
      if (!collection?.id) return
      setItems(current => [collection, ...current.filter(item => item.id !== collection.id)])
      setSelectedId(collection.id)
      setDraft(collection)
      setError('')
    }
    window.addEventListener('hocuspocus:workspace-collection-open', open)
    return () => window.removeEventListener('hocuspocus:workspace-collection-open', open)
  }, [])

  const dirty = useMemo(() => {
    const original = items.find(item => item.id === draft?.id)
    return Boolean(draft && original && JSON.stringify(draft) !== JSON.stringify(original))
  }, [draft, items])

  const select = (item: WorkspaceCollection) => { setSelectedId(item.id); setDraft(item); setError('') }
  const create = async () => {
    const name = newName.trim(); if (!name) return
    setSaving(true); setError('')
    try {
      const created = await createWorkspaceCollection({ name })
      setItems(current => [created, ...current]); setSelectedId(created.id); setDraft(created); setNewName('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }
  const save = async () => {
    if (!draft) return
    setSaving(true); setError('')
    try {
      const changed = await updateWorkspaceCollection(draft)
      setItems(current => current.map(item => item.id === changed.id ? changed : item)); setDraft(changed)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }
  const remove = async () => {
    if (!draft || !window.confirm(`¿Eliminar el Workspace “${draft.name}”? No se borrará ningún proyecto ni asset.`)) return
    setSaving(true); setError('')
    try {
      await deleteWorkspaceCollection(draft.id)
      const remaining = items.filter(item => item.id !== draft.id)
      setItems(remaining); setDraft(remaining[0] || null); setSelectedId(remaining[0]?.id || '')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }

  return (
    <section aria-label="Workspace collections" className="flex h-full min-h-0 overflow-hidden rounded-xl border border-border bg-bg-primary">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-bg-secondary">
        <div className="border-b border-border p-3">
          <div className="flex items-center gap-2 text-sm font-semibold"><FolderKanban size={16} className="text-violet-300" /> Workspaces</div>
          <p className="mt-1 text-[10px] text-text-muted">Colecciones de referencias. No son carpetas de outputs.</p>
          <div className="mt-3 flex gap-1">
            <input aria-label="New Workspace name" value={newName} onChange={event => setNewName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void create() }} placeholder="Nuevo workspace…" className="min-w-0 flex-1 rounded-md border border-border bg-bg-primary px-2 py-1.5 text-xs" />
            <button className={button} disabled={!newName.trim() || saving} onClick={() => void create()} title="Crear Workspace"><Plus size={13} /></button>
          </div>
        </div>
        <nav aria-label="Saved Workspaces" className="min-h-0 flex-1 overflow-y-auto p-2">
          {items.map(item => <button key={item.id} onClick={() => select(item)} className={`mb-1 w-full rounded-lg border p-2 text-left ${item.id === selectedId ? 'border-violet-500/50 bg-violet-500/10' : 'border-transparent hover:bg-bg-hover'}`}>
            <div className="truncate text-xs font-medium text-text-primary">{item.name}</div>
            <div className="mt-1 text-[10px] text-text-muted">{item.project_ids.length} projects · {item.asset_ids.length} assets · {item.production_ids.length} productions</div>
          </button>)}
          {!items.length && !loading && <p className="p-3 text-xs text-text-muted">Crea un Workspace para reunir elementos sin moverlos de sitio.</p>}
        </nav>
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div><h2 className="text-sm font-semibold text-text-primary">{draft?.name || 'Workspace nuevo'}</h2><p className="text-[10px] text-text-muted">Los checks guardan IDs exactos; cambiar un título no rompe la colección.</p></div>
          <div className="flex gap-1"><button className={button} onClick={() => void load()} title="Actualizar"><RefreshCw size={13} className={loading ? 'animate-spin' : ''} /></button>{draft && <><button className={button} disabled={!dirty || saving} onClick={() => void save()}><Save size={13} /> Guardar</button><button className={`${button} text-red-300`} disabled={saving} onClick={() => void remove()}><Trash2 size={13} /></button></>}</div>
        </div>
        {error && <div role="alert" className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{error}</div>}
        {loading && !draft ? <div className="flex items-center justify-center gap-2 p-12 text-xs text-text-muted"><Loader2 size={15} className="animate-spin" /> Cargando…</div> : draft ? <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2"><label className="text-[10px] text-text-muted">Nombre<input value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} className="mt-1 block w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary" /></label><label className="text-[10px] text-text-muted">Descripción<input value={draft.description} onChange={event => setDraft({ ...draft, description: event.target.value })} className="mt-1 block w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary" /></label></div>
          <ReferenceGroup title="Projects" entries={projects.map(item => ({ id: item.id, label: item.title, hint: item.kind }))} selected={draft.project_ids} onToggle={id => setDraft({ ...draft, project_ids: toggle(draft.project_ids, id) })} />
          <ReferenceGroup title="Assets" entries={assets.map(item => ({ id: item.id, label: item.filename, hint: item.kind }))} selected={draft.asset_ids} onToggle={id => setDraft({ ...draft, asset_ids: toggle(draft.asset_ids, id) })} />
          <ReferenceGroup title="Productions" entries={productions.map(item => ({ id: item.id, label: item.title, hint: item.kind }))} selected={draft.production_ids} onToggle={id => setDraft({ ...draft, production_ids: toggle(draft.production_ids, id) })} />
        </div> : null}
      </div>
    </section>
  )
}

function ReferenceGroup({ title, entries, selected, onToggle }: { title: string; entries: Array<{ id: string; label: string; hint: string }>; selected: string[]; onToggle: (id: string) => void }) {
  return <fieldset className="rounded-lg border border-border bg-bg-secondary p-3"><legend className="px-1 text-xs font-semibold text-text-primary">{title} <span className="text-text-muted">({selected.length})</span></legend><div className="mt-1 grid max-h-48 gap-1 overflow-y-auto md:grid-cols-2 xl:grid-cols-3">{entries.map(entry => <label key={entry.id} className="flex cursor-pointer items-start gap-2 rounded p-2 hover:bg-bg-hover"><input type="checkbox" checked={selected.includes(entry.id)} onChange={() => onToggle(entry.id)} /><span className="min-w-0"><span className="block truncate text-xs text-text-primary" title={entry.label}>{entry.label}</span><span className="text-[9px] text-text-muted">{entry.hint} · {entry.id}</span></span></label>)}{!entries.length && <p className="text-[10px] text-text-muted">Todavía no hay elementos de este tipo.</p>}</div></fieldset>
}

export default WorkspaceCollectionsPanel
