import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'

const DEBOUNCE_MS = 300

/** Search box for the gallery toolbar. It shares the library search state
 *  with the navigation bar and searches prompts, models and modes on the
 *  server, matching words as they are typed and ignoring accents. */
export function GallerySearch({ autoFocus = false, onClose }: { autoFocus?: boolean; onClose?: () => void }) {
  const { t } = useUiTranslation('activity')
  const query = useStore(s => s.outputSearchQuery)
  const setQuery = useStore(s => s.setOutputSearchQuery)
  const total = useStore(s => s.outputsTotal)
  const loading = useStore(s => s.outputsLoading)
  const [draft, setDraft] = useState(query)
  const [synced, setSynced] = useState(query)
  const input = useRef<HTMLInputElement>(null)
  // Follow changes made elsewhere (the navigation search, a tab switch).
  if (synced !== query) {
    setSynced(query)
    setDraft(query)
  }

  useEffect(() => {
    if (autoFocus) input.current?.focus()
  }, [autoFocus])

  useEffect(() => {
    if (draft.trim() === query.trim()) return
    const timer = window.setTimeout(() => setQuery(draft), DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [draft, query, setQuery])

  const clear = () => {
    setDraft('')
    setQuery('')
    input.current?.focus()
  }

  return (
    <div role="search" className="flex h-10 min-w-0 flex-1 items-center gap-1.5 rounded-md border border-border/70 bg-bg-secondary px-2 text-xs md:max-w-sm">
      <Search size={14} className="shrink-0 text-text-muted" aria-hidden="true" />
      <input
        ref={input}
        type="search"
        value={draft}
        aria-label={t('gallerySearch.label')}
        placeholder={t('gallerySearch.placeholder')}
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key !== 'Escape') return
          event.stopPropagation()
          if (draft) clear()
          else onClose?.()
        }}
        className="min-w-0 flex-1 bg-transparent text-text-primary outline-none placeholder:text-text-muted [&::-webkit-search-cancel-button]:hidden"
      />
      {query.trim() && !loading && (
        <span className="shrink-0 tabular-nums text-text-muted" aria-live="polite">{t('gallerySearch.results', { count: total })}</span>
      )}
      {(draft || onClose) && (
        <button type="button" onClick={draft ? clear : onClose} aria-label={draft ? t('gallerySearch.clear') : t('gallerySearch.close')}
          title={draft ? t('gallerySearch.clear') : t('gallerySearch.close')}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded text-text-muted hover:bg-white/[0.07] hover:text-text-primary">
          <X size={14} />
        </button>
      )}
    </div>
  )
}

/** Shown instead of the first-run guide when a search finds nothing. */
export function GallerySearchEmpty({ count }: { count: number }) {
  const { t } = useUiTranslation('activity')
  const setQuery = useStore(s => s.setOutputSearchQuery)
  const query = useStore(s => s.outputSearchQuery)
  const loading = useStore(s => s.outputsLoading)
  if (loading || count > 0 || !query.trim()) return null
  return (
    <div role="status" className="flex min-h-[240px] flex-col items-center justify-center gap-3 px-6 text-center">
      <Search size={28} className="text-text-muted" aria-hidden="true" />
      <p className="text-sm text-text-secondary [overflow-wrap:anywhere]">{t('gallerySearch.noResults', { query: query.trim() })}</p>
      <p className="max-w-sm text-xs text-text-muted">{t('gallerySearch.noResultsHint')}</p>
      <button type="button" onClick={() => setQuery('')} className="min-h-11 rounded-lg border border-border px-4 text-sm hover:bg-bg-hover">
        {t('gallerySearch.clear')}
      </button>
    </div>
  )
}
