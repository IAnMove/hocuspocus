import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Activity, BookOpen, Boxes, Clapperboard, FolderKanban, Languages,
  Library, MonitorPlay, Search, Settings, Sparkles, Video, WandSparkles, X,
} from 'lucide-react'
import { setUiLanguage, useUiTranslation, type UiLanguage } from '../../i18n'
import {
  categoryForMediaFilter, type NavigationCategory, WIZARD_NAVIGATION_EVENT,
} from '../../lib/navigationCategories'
import { useStore } from '../../stores/useStore'
import type { GenerationMode, MediaFilter } from '../../types'
import { OutputFolderSelector } from './OutputFolderSelector'

interface MenuItem {
  value?: MediaFilter
  selected?: boolean
  section?: string
  label: string
  description: string
  icon: ReactNode
  action: () => void
}

const PRIMARY_DESTINATIONS = {
  workspaces: { value: 'workspaces' as const },
  activity: { value: 'runs' as const },
}

const DIRECT_GENERATION_MEDIA: Record<GenerationMode, MediaFilter> = {
  image: 'images',
  video: 'videos',
  audio: 'audio',
  model3d: 'model3d',
  avatar: 'avatars',
  tools: 'all',
}

function PrimaryButton({ active, expanded, icon, label, onClick, ariaLabel, category, buttonRef }: {
  active?: boolean
  expanded?: boolean
  icon: ReactNode
  label: string
  onClick?: () => void
  ariaLabel?: string
  category?: NavigationCategory
  buttonRef?: (element: HTMLButtonElement | null) => void
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      role={category ? 'button' : 'tab'}
      aria-selected={category ? undefined : active || false}
      aria-pressed={category ? expanded || false : undefined}
      aria-label={ariaLabel || label}
      onClick={onClick}
      data-navigation-category={category}
      data-navigation-active={active ? 'true' : undefined}
      data-navigation-expanded={expanded ? 'true' : undefined}
      data-wizard-anchor={category ? `navigation.${category}` : undefined}
      className={`hp-navigation-primary relative flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition ${active || expanded ? 'text-text-primary' : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'}`}
    >
      {icon}<span>{label}</span>
    </button>
  )
}

function NavigationBar({ category, title, items, activeValue, barRef }: { category: NavigationCategory; title: string; items: MenuItem[]; activeValue: MediaFilter; barRef: (element: HTMLDivElement | null) => void }) {
  return (
    <div ref={barRef} className="hp-navigation-children relative flex min-w-0 items-center gap-1 overflow-x-auto rounded-lg border px-1.5 py-1" data-navigation-category={category} aria-label={title} role="tablist">
      <div className="flex min-w-max items-center gap-1">
        {items.map(item => (
          <button
            key={item.label}
            type="button"
            role="tab"
            title={item.description}
            aria-label={item.label}
            aria-selected={item.selected ?? item.value === activeValue}
            onClick={item.action}
            className="hp-navigation-child flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[10px] font-medium text-text-secondary transition hover:text-text-primary"
          >
            <span>{item.icon}</span><span>{item.label}</span>
          </button>
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
  const generationMode = useStore(s => s.generationMode)
  const sidebarMode = useStore(s => s.sidebarMode)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const dashboardOpen = useStore(s => s.dashboardOpen)
  const searchQuery = useStore(s => s.outputSearchQuery)
  const setSearchQuery = useStore(s => s.setOutputSearchQuery)
  const [searchOpen, setSearchOpen] = useState(false)
  const [draftQuery, setDraftQuery] = useState(searchQuery)
  const searchRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<number | null>(null)
  const categoryRefs = useRef<Partial<Record<NavigationCategory, HTMLButtonElement | null>>>({})
  const topRowRef = useRef<HTMLDivElement>(null)
  const childBarRef = useRef<HTMLDivElement>(null)
  const magicTimerRef = useRef<number | null>(null)
  const initialCategory = categoryForMediaFilter(mediaFilter) || 'direct-generation'
  const [activeCategory, setActiveCategory] = useState<NavigationCategory | null>(initialCategory)
  const [expandedCategory, setExpandedCategory] = useState<NavigationCategory | null>(initialCategory)
  const language: UiLanguage = String(i18n.resolvedLanguage || i18n.language).startsWith('es') ? 'es' : 'en'

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus()
  }, [searchOpen])

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    useStore.setState({ outputSearchQuery: '', selectedOutput: 0 })
  }, [])

  useEffect(() => {
    const alignJoin = () => {
      if (!expandedCategory) return
      const button = categoryRefs.current[expandedCategory]
      const bar = childBarRef.current
      if (!button || !bar) return
      const buttonBox = button.getBoundingClientRect()
      const barBox = bar.getBoundingClientRect()
      const left = Math.max(0, buttonBox.left - barBox.left)
      const width = Math.max(0, Math.min(buttonBox.width, barBox.width - left))
      bar.style.setProperty('--hp-navigation-notch-left', `${left}px`)
      bar.style.setProperty('--hp-navigation-notch-width', `${width}px`)
    }
    alignJoin()
    const row = topRowRef.current
    row?.addEventListener('scroll', alignJoin, { passive: true })
    window.addEventListener('resize', alignJoin)
    return () => {
      row?.removeEventListener('scroll', alignJoin)
      window.removeEventListener('resize', alignJoin)
    }
  }, [expandedCategory])

  useEffect(() => {
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ category?: NavigationCategory }>).detail
      const category = detail?.category
      if (!category) return
      setActiveCategory(category)
      setExpandedCategory(category)
      const anchor = categoryRefs.current[category]
      if (!anchor) return
      anchor.dataset.wizardMagic = 'active'
      anchor.scrollIntoView?.({ block: 'nearest', inline: 'center', behavior: 'smooth' })
      if (magicTimerRef.current !== null) window.clearTimeout(magicTimerRef.current)
      magicTimerRef.current = window.setTimeout(() => {
        anchor.dataset.wizardMagic = 'confirmed'
        magicTimerRef.current = window.setTimeout(() => {
          delete anchor.dataset.wizardMagic
          magicTimerRef.current = null
        }, 420)
      }, 900)
    }
    window.addEventListener(WIZARD_NAVIGATION_EVENT, reveal)
    return () => {
      window.removeEventListener(WIZARD_NAVIGATION_EVENT, reveal)
      if (magicTimerRef.current !== null) window.clearTimeout(magicTimerRef.current)
    }
  }, [])

  const openFilter = (filter: MediaFilter) => {
    const category = categoryForMediaFilter(filter)
    setActiveCategory(category)
    setExpandedCategory(category)
    setMediaFilter(filter)
  }
  const openDirectGeneration = (mode: GenerationMode) => {
    setActiveCategory('direct-generation')
    setExpandedCategory('direct-generation')
    const state = useStore.getState()
    state.setSettingsOpen(false)
    state.setDashboardOpen(false)
    state.setGenerationMode(mode)
    state.setMediaFilter(DIRECT_GENERATION_MEDIA[mode])
    state.setSidebarMode('studio')
    window.dispatchEvent(new Event('hocuspocus:studio-open'))
  }
  const directGenerationItems: MenuItem[] = [
    { selected: activeCategory === 'direct-generation' && generationMode === 'image', label: t('directModes.image'), description: t('descriptions.directImage'), icon: <Sparkles size={15} />, action: () => openDirectGeneration('image') },
    { selected: activeCategory === 'direct-generation' && generationMode === 'video', label: t('directModes.video'), description: t('descriptions.directVideo'), icon: <Video size={15} />, action: () => openDirectGeneration('video') },
    { selected: activeCategory === 'direct-generation' && generationMode === 'audio', label: t('directModes.audio'), description: t('descriptions.directAudio'), icon: <Activity size={15} />, action: () => openDirectGeneration('audio') },
    { selected: activeCategory === 'direct-generation' && generationMode === 'model3d', label: t('directModes.model3d'), description: t('descriptions.direct3d'), icon: <Boxes size={15} />, action: () => openDirectGeneration('model3d') },
    { selected: activeCategory === 'direct-generation' && generationMode === 'avatar', label: t('directModes.avatar'), description: t('descriptions.directEdit'), icon: <WandSparkles size={15} />, action: () => openDirectGeneration('avatar') },
    { selected: activeCategory === 'direct-generation' && generationMode === 'tools', label: t('directModes.tools'), description: t('descriptions.directTools'), icon: <WandSparkles size={15} />, action: () => openDirectGeneration('tools') },
  ]
  const studioItems: MenuItem[] = [
    { value: 'stories', label: t('tabs.storyLab'), description: t('descriptions.storyLab'), icon: <BookOpen size={15} />, action: () => openFilter('stories') },
    { value: 'series', label: t('tabs.seriesLab'), description: t('descriptions.seriesLab'), icon: <Library size={15} />, action: () => openFilter('series') },
    { value: 'comics', label: t('tabs.comics'), description: t('descriptions.comics'), icon: <BookOpen size={15} />, action: () => openFilter('comics') },
    { value: 'characters', label: t('tabs.characters'), description: t('descriptions.characters'), icon: <WandSparkles size={15} />, action: () => openFilter('characters') },
    { value: 'scene3d', label: t('tabs.scene3d'), description: t('descriptions.video3d'), icon: <MonitorPlay size={15} />, action: () => openFilter('scene3d') },
    { value: 'animate3d', label: t('tabs.animate3d'), description: t('descriptions.animate3d'), icon: <MonitorPlay size={15} />, action: () => openFilter('animate3d') },
  ]
  const productionItems: MenuItem[] = [
    { selected: activeCategory === 'production' && sidebarMode === 'director' && sidebarOpen, label: t('labs.director'), description: t('descriptions.director'), icon: <Clapperboard size={15} />, action: () => {
      setActiveCategory('production')
      setExpandedCategory('production')
      useStore.getState().setSidebarMode('director')
      window.dispatchEvent(new Event('maestro:director-open'))
    } },
    { value: 'videoeditor', label: t('tabs.videoEditor'), description: t('descriptions.editor'), icon: <Video size={15} />, action: () => openFilter('videoeditor') },
    { selected: activeCategory === 'production' && dashboardOpen, label: t('tabs.productions'), description: t('descriptions.productions'), icon: <MonitorPlay size={15} />, action: () => {
      setActiveCategory('production')
      setExpandedCategory('production')
      const state = useStore.getState()
      state.setSettingsOpen(false)
      state.setSidebarOpen(false)
      state.setDashboardOpen(true)
    } },
  ]
  const mediaItems: MenuItem[] = [
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

  const selectCategory = (category: NavigationCategory) => {
    setActiveCategory(category)
    setExpandedCategory(category)
  }
  const expandedItems = expandedCategory === 'direct-generation' ? directGenerationItems
    : expandedCategory === 'studios' ? studioItems
    : expandedCategory === 'production' ? productionItems
    : expandedCategory === 'media' ? mediaItems
    : []
  const expandedTitle = expandedCategory ? t(`menu.${expandedCategory === 'direct-generation' ? 'directGeneration' : expandedCategory}`) : ''

  return (
    <nav aria-label={t('aria.sections')} className="flex min-w-0 flex-1 flex-col rounded-xl border border-border bg-bg-tertiary/70 p-1">
      <div ref={topRowRef} className="flex min-w-0 flex-nowrap items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <PrimaryButton active={activeCategory === 'direct-generation'} expanded={expandedCategory === 'direct-generation'} category="direct-generation" buttonRef={element => { categoryRefs.current['direct-generation'] = element }} icon={<Sparkles size={14} />} label={t('primary.directGeneration')} onClick={() => selectCategory('direct-generation')} />
        <PrimaryButton active={activeCategory === 'studios'} expanded={expandedCategory === 'studios'} category="studios" buttonRef={element => { categoryRefs.current.studios = element }} icon={<BookOpen size={14} />} label={t('primary.studios')} onClick={() => selectCategory('studios')} />
        <PrimaryButton active={activeCategory === 'production'} expanded={expandedCategory === 'production'} category="production" buttonRef={element => { categoryRefs.current.production = element }} icon={<Clapperboard size={14} />} label={t('primary.production')} onClick={() => selectCategory('production')} />
        <PrimaryButton active={activeCategory === 'media'} expanded={expandedCategory === 'media'} category="media" buttonRef={element => { categoryRefs.current.media = element }} icon={<Library size={14} />} label={t('primary.media')} onClick={() => selectCategory('media')} />
        <PrimaryButton active={mediaFilter === PRIMARY_DESTINATIONS.workspaces.value} icon={<FolderKanban size={14} />} label={t('tabs.workspaces')} onClick={() => openFilter(PRIMARY_DESTINATIONS.workspaces.value)} />
        <PrimaryButton active={mediaFilter === PRIMARY_DESTINATIONS.activity.value} icon={<Activity size={14} />} label={t('primary.activity')} ariaLabel={`${t('tabs.runs')} · ${t('primary.activity')}`} onClick={() => openFilter(PRIMARY_DESTINATIONS.activity.value)} />

        <div className="ml-auto flex items-center gap-1">
          <OutputFolderSelector />
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
      </div>
      {expandedCategory && <NavigationBar barRef={element => { childBarRef.current = element }} category={expandedCategory} title={expandedTitle} items={expandedItems} activeValue={mediaFilter} />}
    </nav>
  )
}
