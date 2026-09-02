import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Activity, BookOpen, Boxes, ChevronDown, Clapperboard, FolderKanban, Languages,
  Library, MonitorPlay, Search, Settings, Sparkles, Video, WandSparkles, X,
} from 'lucide-react'
import { setUiLanguage, useUiTranslation, type UiLanguage } from '../../i18n'
import { useStore } from '../../stores/useStore'
import type { GenerationMode, MediaFilter } from '../../types'

interface MenuItem {
  value?: MediaFilter
  section?: string
  label: string
  description: string
  icon: ReactNode
  action: () => void
}

const CREATE_FILTERS = new Set<MediaFilter>([
  'stories', 'series', 'comics', 'videoeditor', 'scene3d', 'animate3d', 'characters',
])
const LIBRARY_FILTERS = new Set<MediaFilter>([
  'all', 'assets', 'projects', 'images', 'videos', 'videoclips', 'trailers',
  'series_episodes', 'audio', 'model3d', 'scenes', 'styles', 'avatars', 'multiclip', 'favorites',
])
const PRIMARY_DESTINATIONS = {
  workspaces: { value: 'workspaces' as const },
  activity: { value: 'runs' as const },
}

function PrimaryButton({ active, icon, label, onClick, menu, ariaLabel }: {
  active?: boolean
  icon: ReactNode
  label: string
  onClick?: () => void
  menu?: ReactNode
  ariaLabel?: string
}) {
  if (menu) {
    return (
      <details className="group relative">
        <summary className={`flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${active ? 'bg-bg-active text-text-primary' : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'}`}>
          {icon}<span>{label}</span><ChevronDown size={12} className="transition group-open:rotate-180" />
        </summary>
        {menu}
      </details>
    )
  }
  return (
    <button type="button" role="tab" aria-selected={active || false} aria-label={ariaLabel} onClick={onClick} className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${active ? 'bg-bg-active text-text-primary' : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'}`}>
      {icon}<span>{label}</span>
    </button>
  )
}

function NavigationMenu({ title, items, activeValue }: { title: string; items: MenuItem[]; activeValue: MediaFilter }) {
  return (
    <div className="absolute left-0 top-full z-50 mt-2 max-h-[calc(100vh-6rem)] w-80 overflow-y-auto rounded-xl border border-border bg-bg-secondary p-2 shadow-2xl">
      <p className="px-2 pb-1 pt-0.5 text-[9px] font-semibold uppercase tracking-[0.18em] text-text-muted">{title}</p>
      <div className="grid gap-1">
        {items.map(item => (
          <div key={item.label}>
            {item.section && <p className="mt-1 border-t border-border/60 px-2 pb-1 pt-2 text-[8px] font-semibold uppercase tracking-[0.18em] text-accent-blue first:mt-0 first:border-0 first:pt-1">{item.section}</p>}
            <button
              type="button"
              role="tab"
              aria-label={item.label}
              aria-selected={item.value === activeValue}
              onClick={event => {
                item.action()
                event.currentTarget.closest('details')?.removeAttribute('open')
              }}
              className="flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left hover:bg-bg-hover"
            >
              <span className="mt-0.5 text-accent-blue">{item.icon}</span>
              <span className="min-w-0">
                <span className="block text-xs font-medium text-text-primary">{item.label}</span>
                <span className="block text-[10px] leading-relaxed text-text-muted">{item.description}</span>
              </span>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export function TabFilter() {
  const { t, i18n } = useUiTranslation('navigation')
  const mediaFilter = useStore(s => s.mediaFilter)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const developerMode = useStore(s => s.developerMode)
  const searchQuery = useStore(s => s.outputSearchQuery)
  const setSearchQuery = useStore(s => s.setOutputSearchQuery)
  const [searchOpen, setSearchOpen] = useState(false)
  const [draftQuery, setDraftQuery] = useState(searchQuery)
  const searchRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<number | null>(null)
  const language: UiLanguage = String(i18n.resolvedLanguage || i18n.language).startsWith('es') ? 'es' : 'en'

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus()
  }, [searchOpen])

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    useStore.setState({ outputSearchQuery: '', selectedOutput: 0 })
  }, [])

  const openFilter = (filter: MediaFilter) => setMediaFilter(filter)
  const openDirectGeneration = (mode: GenerationMode) => {
    useStore.getState().setGenerationMode(mode)
    useStore.getState().setSidebarMode('studio')
    window.dispatchEvent(new Event('hocuspocus:studio-open'))
  }
  const createItems: MenuItem[] = [
    { section: t('menu.directGeneration'), label: t('directModes.image'), description: t('descriptions.directImage'), icon: <Sparkles size={15} />, action: () => openDirectGeneration('image') },
    { label: t('directModes.video'), description: t('descriptions.directVideo'), icon: <Video size={15} />, action: () => openDirectGeneration('video') },
    { label: t('directModes.audio'), description: t('descriptions.directAudio'), icon: <Activity size={15} />, action: () => openDirectGeneration('audio') },
    { label: t('directModes.model3d'), description: t('descriptions.direct3d'), icon: <Boxes size={15} />, action: () => openDirectGeneration('model3d') },
    { label: t('directModes.avatar'), description: t('descriptions.directEdit'), icon: <WandSparkles size={15} />, action: () => openDirectGeneration('avatar') },
    { label: t('directModes.tools'), description: t('descriptions.directTools'), icon: <WandSparkles size={15} />, action: () => openDirectGeneration('tools') },
    { section: t('menu.guidedCreation'), label: t('labs.director'), description: t('descriptions.director'), icon: <Clapperboard size={15} />, action: () => {
      useStore.getState().setSidebarMode('director')
      window.dispatchEvent(new Event('maestro:director-open'))
    } },
    { value: 'stories', label: t('tabs.storyLab'), description: t('descriptions.storyLab'), icon: <BookOpen size={15} />, action: () => openFilter('stories') },
    { value: 'series', label: t('tabs.seriesLab'), description: t('descriptions.seriesLab'), icon: <Library size={15} />, action: () => openFilter('series') },
    { value: 'comics', label: t('tabs.comics'), description: t('descriptions.comics'), icon: <BookOpen size={15} />, action: () => openFilter('comics') },
    { value: 'videoeditor', label: t('tabs.videoEditor'), description: t('descriptions.editor'), icon: <Video size={15} />, action: () => openFilter('videoeditor') },
    { value: 'scene3d', label: t('tabs.scene3d'), description: t('descriptions.video3d'), icon: <MonitorPlay size={15} />, action: () => openFilter('scene3d') },
    { value: 'characters', label: t('tabs.characters'), description: t('descriptions.characters'), icon: <WandSparkles size={15} />, action: () => openFilter('characters') },
  ]
  const libraryItems: MenuItem[] = [
    { value: 'projects', label: t('tabs.projects'), description: t('descriptions.projects'), icon: <FolderKanban size={15} />, action: () => openFilter('projects') },
    { value: 'assets', label: t('tabs.assets'), description: t('descriptions.assets'), icon: <Boxes size={15} />, action: () => openFilter('assets') },
    { value: 'all', label: t('tabs.all'), description: t('descriptions.allOutputs'), icon: <Library size={15} />, action: () => openFilter('all') },
    { value: 'images', label: t('tabs.images'), description: t('descriptions.mediaFilters'), icon: <Sparkles size={15} />, action: () => openFilter('images') },
    { value: 'videos', label: t('tabs.videos'), description: t('descriptions.mediaFilters'), icon: <Video size={15} />, action: () => openFilter('videos') },
    { value: 'videoclips', label: t('tabs.videoclips'), description: t('descriptions.mediaFilters'), icon: <Video size={15} />, action: () => openFilter('videoclips') },
    { value: 'trailers', label: t('tabs.trailers'), description: t('descriptions.mediaFilters'), icon: <Video size={15} />, action: () => openFilter('trailers') },
    { value: 'series_episodes', label: t('tabs.episodes'), description: t('descriptions.mediaFilters'), icon: <Video size={15} />, action: () => openFilter('series_episodes') },
    { value: 'audio', label: t('tabs.audio'), description: t('descriptions.mediaFilters'), icon: <Activity size={15} />, action: () => openFilter('audio') },
    { value: 'model3d', label: t('tabs.model3d'), description: t('descriptions.mediaFilters'), icon: <Boxes size={15} />, action: () => openFilter('model3d') },
    { value: 'favorites', label: t('tabs.favorites'), description: t('descriptions.mediaFilters'), icon: <Sparkles size={15} />, action: () => openFilter('favorites') },
    ...(developerMode ? [{ value: 'auditdev' as const, label: t('tabs.auditDev'), description: t('descriptions.mediaFilters'), icon: <Activity size={15} />, action: () => openFilter('auditdev') }] : []),
  ]

  const handleSearchChange = (value: string) => {
    setDraftQuery(value)
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null
      setSearchQuery(value)
    }, 400)
  }
  const closeSearch = () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    debounceRef.current = null
    setDraftQuery('')
    setSearchOpen(false)
    if (useStore.getState().outputSearchQuery) setSearchQuery('')
  }

  return (
    <nav aria-label={t('aria.sections')} className="flex min-w-0 flex-1 items-center gap-1 rounded-xl border border-border bg-bg-tertiary/70 p-1">
      <PrimaryButton active={CREATE_FILTERS.has(mediaFilter)} icon={<Sparkles size={14} />} label={t('primary.create')} menu={<NavigationMenu title={t('menu.create')} items={createItems} activeValue={mediaFilter} />} />
      <PrimaryButton active={LIBRARY_FILTERS.has(mediaFilter)} icon={<Library size={14} />} label={t('primary.library')} menu={<NavigationMenu title={t('menu.library')} items={libraryItems} activeValue={mediaFilter} />} />
      <PrimaryButton active={mediaFilter === PRIMARY_DESTINATIONS.workspaces.value} icon={<FolderKanban size={14} />} label={t('tabs.workspaces')} onClick={() => openFilter(PRIMARY_DESTINATIONS.workspaces.value)} />
      <PrimaryButton active={mediaFilter === PRIMARY_DESTINATIONS.activity.value} icon={<Activity size={14} />} label={t('primary.activity')} ariaLabel={`${t('tabs.runs')} · ${t('primary.activity')}`} onClick={() => openFilter(PRIMARY_DESTINATIONS.activity.value)} />

      <div className="ml-auto flex items-center gap-1">
        {searchOpen ? (
          <div className="flex items-center gap-1 rounded-lg border border-border bg-bg-secondary px-2 py-0.5">
            <Search size={12} className="shrink-0 text-text-muted" />
            <input ref={searchRef} value={draftQuery} onChange={event => handleSearchChange(event.target.value)} placeholder={t('search.placeholder')} className="w-24 bg-transparent text-xs text-text-primary outline-none placeholder:text-text-muted md:w-36" />
            <button type="button" onClick={closeSearch} aria-label={t('search.close')} className="text-text-muted hover:text-text-secondary"><X size={12} /></button>
          </div>
        ) : (
          <button type="button" onClick={() => { setDraftQuery(searchQuery); setSearchOpen(true) }} className={`rounded-lg p-1.5 ${searchQuery ? 'bg-accent-blue/10 text-accent-blue' : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'}`} title="Search outputs" aria-label={t('search.open')}>
            <Search size={14} />
          </button>
        )}
        <label className="flex items-center gap-1 rounded-lg px-2 py-1 text-text-muted hover:bg-bg-hover" title="Interface language">
          <Languages size={14} />
          <select value={language} onChange={event => { void setUiLanguage(event.target.value as UiLanguage) }} className="cursor-pointer bg-transparent text-[10px] font-medium text-text-secondary outline-none" aria-label="Quick interface language">
            <option value="es">ES</option>
            <option value="en">EN</option>
          </select>
        </label>
        <button type="button" onClick={() => window.dispatchEvent(new Event('hocuspocus:settings-open'))} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-text-muted transition hover:bg-bg-hover hover:text-text-primary" aria-label="Settings">
          <Settings size={14} /><span>Settings</span>
        </button>
      </div>
    </nav>
  )
}
