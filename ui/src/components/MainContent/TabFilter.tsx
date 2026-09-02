import { useState, useRef, useEffect } from 'react'
import { Heart, Film, Search, X, Box, PersonStanding, BookOpen, Library, Palette, Layers, ShieldAlert } from 'lucide-react'
import type { ParseKeys } from 'i18next'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import type { MediaFilter } from '../../types'
import { HorizontalScrollTabs } from '../common/HorizontalScrollTabs'

type NavigationKey = ParseKeys<'navigation'>

const tabs: { value: MediaFilter; labelKey: NavigationKey; shortKey: NavigationKey; icon?: string }[] = [
  { value: 'all', labelKey: 'tabs.all', shortKey: 'short.all' },
  { value: 'assets', labelKey: 'tabs.assets', shortKey: 'short.assets', icon: 'layers' },
  { value: 'projects', labelKey: 'tabs.projects', shortKey: 'short.projects', icon: 'library' },
  { value: 'workspaces', labelKey: 'tabs.workspaces', shortKey: 'short.workspaces', icon: 'layers' },
  { value: 'images', labelKey: 'tabs.images', shortKey: 'short.images' },
  { value: 'videos', labelKey: 'tabs.videos', shortKey: 'short.videos' },
  { value: 'videoclips', labelKey: 'tabs.videoclips', shortKey: 'short.videoclips' },
  { value: 'trailers', labelKey: 'tabs.trailers', shortKey: 'short.trailers' },
  { value: 'series_episodes', labelKey: 'tabs.episodes', shortKey: 'short.episodes' },
  { value: 'audio', labelKey: 'tabs.audio', shortKey: 'short.audio' },
  { value: 'model3d', labelKey: 'tabs.model3d', shortKey: 'short.model3d', icon: 'box' },
  { value: 'scenes', labelKey: 'tabs.scenes', shortKey: 'short.scenes', icon: 'film' },
  { value: 'stories', labelKey: 'tabs.storyLab', shortKey: 'short.storyLab', icon: 'library' },
  { value: 'series', labelKey: 'tabs.seriesLab', shortKey: 'short.seriesLab', icon: 'library' },
  { value: 'runs', labelKey: 'tabs.runs', shortKey: 'short.runs', icon: 'layers' },
  { value: 'characters', labelKey: 'tabs.characters', shortKey: 'short.characters', icon: 'person' },
  { value: 'styles', labelKey: 'tabs.styles', shortKey: 'short.styles', icon: 'palette' },
  { value: 'comics', labelKey: 'tabs.comics', shortKey: 'short.comics', icon: 'book' },
  { value: 'videoeditor', labelKey: 'tabs.videoEditor', shortKey: 'short.videoEditor', icon: 'film' },
  { value: 'scene3d', labelKey: 'tabs.scene3d', shortKey: 'short.scene3d', icon: 'film' },
  { value: 'animate3d', labelKey: 'tabs.animate3d', shortKey: 'short.animate3d', icon: 'person' },
  { value: 'avatars', labelKey: 'tabs.edits', shortKey: 'short.edits' },
  { value: 'multiclip', labelKey: 'tabs.multiclip', shortKey: 'short.multiclip', icon: 'film' },
  { value: 'auditdev', labelKey: 'tabs.auditDev', shortKey: 'short.auditDev', icon: 'shield' },
  { value: 'favorites', labelKey: 'tabs.favorites', shortKey: 'short.favorites', icon: 'heart' },
]

export function TabFilter() {
  const { t } = useUiTranslation('navigation')
  const mediaFilter = useStore(s => s.mediaFilter)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const developerMode = useStore(s => s.developerMode)
  const searchQuery = useStore(s => s.outputSearchQuery)
  const setSearchQuery = useStore(s => s.setOutputSearchQuery)
  const visibleTabs = tabs.filter(tab => tab.value !== 'auditdev' || developerMode)
  const [searchOpen, setSearchOpen] = useState(false)
  const [draftQuery, setDraftQuery] = useState(searchQuery)
  const searchRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    if (searchOpen && searchRef.current) searchRef.current.focus()
  }, [searchOpen])

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    // Unmounting the filter must not leave a hidden backend search active.
    // Set the store directly so teardown does not start a needless reload.
    useStore.setState({ outputSearchQuery: '', selectedOutput: 0 })
  }, [])

  const cancelPendingSearch = () => {
    if (debounceRef.current === null) return
    window.clearTimeout(debounceRef.current)
    debounceRef.current = null
  }

  const handleSearchChange = (val: string) => {
    setDraftQuery(val)
    cancelPendingSearch()
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null
      setSearchQuery(val)
    }, 400)
  }

  const closeSearch = () => {
    cancelPendingSearch()
    setDraftQuery('')
    setSearchOpen(false)
    // A pending draft has never reached the store, so avoid an unnecessary
    // normal-output reload when the canonical query is already empty.
    if (useStore.getState().outputSearchQuery) setSearchQuery('')
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <HorizontalScrollTabs
        activeKey={mediaFilter}
        ariaLabel={t('aria.sections')}
        className="flex-1"
        viewportClassName="flex gap-0.5 bg-bg-tertiary rounded-lg p-0.5 border border-border"
      >
        {visibleTabs.map(tab => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={mediaFilter === tab.value}
            data-scroll-key={tab.value}
            onClick={() => setMediaFilter(tab.value)}
            className={`px-2 md:px-3 py-1 md:py-1.5 rounded-md text-[10px] md:text-xs font-medium transition-all flex items-center gap-1 whitespace-nowrap shrink-0 ${
              mediaFilter === tab.value
                ? tab.value === 'favorites' ? 'bg-red-500/20 text-chip-red'
                : tab.value === 'multiclip' || tab.value === 'videoclips' || tab.value === 'trailers' || tab.value === 'series_episodes' ? 'bg-purple-500/20 text-chip-purple'
                : tab.value === 'auditdev' ? 'bg-amber-500/20 text-amber-200'
                : 'bg-bg-active text-text-primary'
                : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            {tab.icon === 'heart' && <Heart size={11} fill={mediaFilter === 'favorites' ? 'currentColor' : 'none'} />}
            {tab.icon === 'film' && <Film size={11} />}
            {tab.icon === 'box' && <Box size={11} />}
            {tab.icon === 'person' && <PersonStanding size={11} />}
            {tab.icon === 'book' && <BookOpen size={11} />}
            {tab.icon === 'library' && <Library size={11} />}
            {tab.icon === 'palette' && <Palette size={11} />}
            {tab.icon === 'layers' && <Layers size={11} />}
            {tab.icon === 'shield' && <ShieldAlert size={11} />}
            <span className="hidden md:inline">{t(tab.labelKey)}</span>
            <span className="md:hidden">{t(tab.shortKey)}</span>
          </button>
        ))}
      </HorizontalScrollTabs>

      {/* Search */}
      {searchOpen ? (
        <div className="flex items-center gap-1 bg-bg-tertiary border border-border rounded-lg px-2 py-0.5">
          <Search size={12} className="text-text-muted shrink-0" />
          <input
            ref={searchRef}
            type="text"
            value={draftQuery}
            onChange={e => handleSearchChange(e.target.value)}
            placeholder="Search..."
            className="bg-transparent text-xs text-text-primary placeholder:text-text-muted focus:outline-none w-24 md:w-36"
          />
          <button type="button" onClick={closeSearch} aria-label="Close search"
            className="text-text-muted hover:text-text-secondary">
            <X size={12} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => { setDraftQuery(searchQuery); setSearchOpen(true) }}
          className={`p-1.5 rounded-lg transition-colors ${searchQuery ? 'text-accent-blue bg-accent-blue/10' : 'text-text-muted hover:text-text-secondary hover:bg-bg-hover'}`}
          title="Search outputs"
        >
          <Search size={14} />
        </button>
      )}
    </div>
  )
}
