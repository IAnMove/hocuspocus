import { useState, useRef, useEffect } from 'react'
import { Heart, Film, Search, X, Box, PersonStanding, BookOpen, Library } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import type { MediaFilter } from '../../types'
import { HorizontalScrollTabs } from '../common/HorizontalScrollTabs'

const tabs: { value: MediaFilter; label: string; shortLabel: string; icon?: string }[] = [
  { value: 'all', label: 'All', shortLabel: 'All' },
  { value: 'images', label: 'Images', shortLabel: 'Img' },
  { value: 'videos', label: 'Videos', shortLabel: 'Vid' },
  { value: 'audio', label: 'Audio', shortLabel: 'Aud' },
  { value: 'model3d', label: '3D', shortLabel: '3D', icon: 'box' },
  { value: 'scenes', label: 'Scenes', shortLabel: 'Scn', icon: 'film' },
  { value: 'stories', label: 'Story Lab', shortLabel: 'Lab', icon: 'library' },
  { value: 'comics', label: 'Comics', shortLabel: 'Comic', icon: 'book' },
  { value: 'videoeditor', label: 'Video Editor', shortLabel: 'Edit', icon: 'film' },
  { value: 'scene3d', label: '3D Video', shortLabel: '3DV', icon: 'film' },
  { value: 'animate3d', label: 'Animate', shortLabel: 'Anim', icon: 'person' },
  { value: 'avatars', label: 'Edits', shortLabel: 'Edit' },
  { value: 'multiclip', label: 'Multi-clip', shortLabel: 'MC', icon: 'film' },
  { value: 'favorites', label: 'Favorites', shortLabel: '', icon: 'heart' },
]

export function TabFilter() {
  const mediaFilter = useStore(s => s.mediaFilter)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const searchQuery = useStore(s => s.outputSearchQuery)
  const setSearchQuery = useStore(s => s.setOutputSearchQuery)
  const [searchOpen, setSearchOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (searchOpen && searchRef.current) searchRef.current.focus()
  }, [searchOpen])

  const handleSearchChange = (val: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchQuery(val), 400)
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <HorizontalScrollTabs
        activeKey={mediaFilter}
        ariaLabel="Workspace sections"
        className="flex-1"
        viewportClassName="flex gap-0.5 bg-bg-tertiary rounded-lg p-0.5 border border-border"
      >
        {tabs.map(tab => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={mediaFilter === tab.value}
            data-scroll-key={tab.value}
            onClick={() => setMediaFilter(tab.value)}
            className={`px-2 md:px-3 py-1 md:py-1.5 rounded-md text-[10px] md:text-xs font-medium transition-all flex items-center gap-1 whitespace-nowrap shrink-0 ${
              mediaFilter === tab.value
                ? tab.value === 'favorites' ? 'bg-red-500/20 text-red-400'
                : tab.value === 'multiclip' ? 'bg-purple-500/20 text-purple-400'
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
            <span className="hidden md:inline">{tab.label}</span>
            <span className="md:hidden">{tab.shortLabel}</span>
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
            defaultValue={searchQuery}
            onChange={e => handleSearchChange(e.target.value)}
            placeholder="Search..."
            className="bg-transparent text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none w-24 md:w-36"
          />
          <button onClick={() => { setSearchOpen(false); if (searchQuery) setSearchQuery('') }}
            className="text-text-muted hover:text-text-secondary">
            <X size={12} />
          </button>
        </div>
      ) : (
        <button
          onClick={() => setSearchOpen(true)}
          className={`p-1.5 rounded-lg transition-colors ${searchQuery ? 'text-accent-blue bg-accent-blue/10' : 'text-text-muted hover:text-text-secondary hover:bg-bg-hover'}`}
          title="Search outputs"
        >
          <Search size={14} />
        </button>
      )}
    </div>
  )
}
