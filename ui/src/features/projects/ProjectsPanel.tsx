import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Box, Boxes, Clapperboard, Copy, ExternalLink, Film, Loader2, RefreshCw, Search, UserRound } from 'lucide-react'
import { fetchProjects, type ProjectCatalogItem, type ProjectKind } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { openProject } from './openProject'

const PAGE_SIZE = 100
const kinds: Array<{ value: ProjectKind | ''; label: string }> = [
  { value: '', label: 'Todos' },
  { value: 'story', label: 'Stories' },
  { value: 'series', label: 'Series' },
  { value: 'episode', label: 'Episodios' },
  { value: 'comic', label: 'Cómics' },
  { value: 'scene3d', label: 'Escenas 3D' },
  { value: 'character_kit', label: 'Character Kits' },
  { value: 'video_editor', label: 'Video Editor' },
]

function projectIcon(kind: ProjectKind) {
  if (kind === 'story') return <BookOpen size={17} />
  if (kind === 'series') return <Boxes size={17} />
  if (kind === 'episode') return <Clapperboard size={17} />
  if (kind === 'comic') return <Film size={17} />
  if (kind === 'scene3d') return <Box size={17} />
  if (kind === 'character_kit') return <UserRound size={17} />
  return <Film size={17} />
}

function formatDate(value?: string | null) {
  if (!value) return 'Fecha no disponible'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Fecha no disponible' : date.toLocaleString()
}

export function ProjectsPanel() {
  const workspaces = useStore(state => state.workspaces)
  const loadWorkspaces = useStore(state => state.loadWorkspaces)
  const [projects, setProjects] = useState<ProjectCatalogItem[]>([])
  const [total, setTotal] = useState(0)
  const [warningCount, setWarningCount] = useState(0)
  const [kind, setKind] = useState<ProjectKind | ''>('')
  const [workspace, setWorkspace] = useState('')
  const [draftSearch, setDraftSearch] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [openingId, setOpeningId] = useState('')
  const requestRef = useRef(0)

  const load = useCallback(async (append = false, offset = 0) => {
    const request = ++requestRef.current
    if (append) setLoadingMore(true)
    else setLoading(true)
    setError('')
    try {
      const result = await fetchProjects({
        search, kind: kind || undefined, workspace: workspace || undefined,
        limit: PAGE_SIZE, offset,
      })
      if (request !== requestRef.current) return
      setProjects(current => append ? [...current, ...result.projects.filter(
        candidate => !current.some(item => item.id === candidate.id),
      )] : result.projects)
      setTotal(result.total)
      setWarningCount(result.warnings.length)
    } catch (reason) {
      if (request === requestRef.current) {
        setError(reason instanceof Error ? reason.message : 'No se pudo cargar el registro')
      }
    } finally {
      if (request === requestRef.current) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [kind, search, workspace])

  useEffect(() => { void loadWorkspaces() }, [loadWorkspaces])
  useEffect(() => { void load(false) }, [load])
  useEffect(() => () => { requestRef.current += 1 }, [])

  const workspaceOptions = useMemo(() => [
    { name: '', label: 'Todos los workspaces' },
    ...workspaces.map(item => ({ name: item.name, label: item.name })),
  ], [workspaces])

  const copyId = async (project: ProjectCatalogItem) => {
    try { await navigator.clipboard.writeText(project.id) } catch { /* unavailable clipboard */ }
  }

  const open = async (project: ProjectCatalogItem) => {
    setOpeningId(project.id)
    setError('')
    try {
      await openProject(project)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo abrir el proyecto')
    } finally {
      setOpeningId('')
    }
  }

  return (
    <section aria-label="All projects" className="flex h-full min-h-0 flex-col bg-bg-primary">
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <Boxes size={16} className="text-violet-300" /> Projects
        </div>
        <span className="text-[10px] text-text-muted">{total} proyectos durables</span>
        {warningCount > 0 && <span className="text-[10px] text-amber-300">{warningCount} fuentes no legibles</span>}
        <div className="min-w-0 flex-1" />
        <form
          className="flex items-center gap-1 rounded-md border border-border bg-bg-secondary px-2"
          onSubmit={event => { event.preventDefault(); setSearch(draftSearch.trim()) }}
        >
          <Search size={12} className="text-text-muted" />
          <input
            value={draftSearch}
            onChange={event => setDraftSearch(event.target.value)}
            placeholder="Buscar título, ID o tipo…"
            className="w-52 bg-transparent py-1.5 text-xs text-text-primary outline-none"
          />
        </form>
        <select
          aria-label="Project kind"
          value={kind}
          onChange={event => setKind(event.target.value as ProjectKind | '')}
          className="rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary"
        >
          {kinds.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select
          aria-label="Project workspace"
          value={workspace}
          onChange={event => setWorkspace(event.target.value)}
          className="rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary"
        >
          {workspaceOptions.map(item => <option key={item.name} value={item.name}>{item.label}</option>)}
        </select>
        <button
          type="button"
          onClick={() => void load(false)}
          className="rounded-md border border-border bg-bg-secondary p-1.5 text-text-muted hover:text-text-primary"
          title="Actualizar registro"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {error && <div role="alert" className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{error}</div>}
        {loading && !projects.length ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-text-muted"><Loader2 size={16} className="animate-spin" /> Leyendo proyectos…</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {projects.map(project => (
              <article key={project.id} className="rounded-lg border border-border bg-bg-secondary p-3">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 text-violet-300">{projectIcon(project.kind)}</span>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-xs font-medium text-text-primary" title={project.title}>{project.title}</h3>
                    <p className="mt-0.5 text-[10px] text-text-muted">{project.kind}{project.subtype ? ` · ${project.subtype}` : ''}</p>
                  </div>
                  <button type="button" onClick={() => void copyId(project)} title="Copiar ID" aria-label={`Copiar ID de ${project.title}`} className="p-1 text-text-muted hover:text-text-primary"><Copy size={12} /></button>
                </div>
                <p className="mt-3 text-[10px] text-text-secondary">{formatDate(project.updated_at)}</p>
                {project.parent && <p className="mt-1 truncate text-[9px] text-text-muted" title={project.parent.id}>Pertenece a {project.parent.kind}: {project.parent.id}</p>}
                <div className="mt-2 flex flex-wrap gap-1">
                  {project.workspace_ids.map(name => <span key={name} className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[9px] text-text-muted">{name}</span>)}
                  {project.revision != null && <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[9px] text-violet-200">r{project.revision}</span>}
                </div>
                <button type="button" disabled={Boolean(openingId)} onClick={() => void open(project)} className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-1.5 text-[10px] text-violet-200 disabled:opacity-50">
                  {openingId === project.id ? <Loader2 size={11} className="animate-spin" /> : <ExternalLink size={11} />} Abrir proyecto
                </button>
              </article>
            ))}
          </div>
        )}
        {!loading && !projects.length && !error && <p className="p-8 text-center text-xs text-text-muted">No hay proyectos que coincidan con estos filtros.</p>}
        {projects.length < total && (
          <button type="button" disabled={loadingMore} onClick={() => void load(true, projects.length)} className="mx-auto mt-4 flex items-center gap-2 rounded-md border border-border bg-bg-secondary px-4 py-2 text-xs text-text-secondary disabled:opacity-50">
            {loadingMore && <Loader2 size={13} className="animate-spin" />} Cargar más
          </button>
        )}
      </div>
    </section>
  )
}
