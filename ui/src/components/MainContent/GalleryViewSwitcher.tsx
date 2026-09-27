import { useTranslation } from 'react-i18next'
import { Rows3, LayoutGrid, Columns3 } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import type { GalleryView } from '../../stores/gallerySlice'

const VIEWS = [
  { id: 'feed', icon: Rows3 },
  { id: 'grid', icon: LayoutGrid },
  { id: 'masonry', icon: Columns3 },
] as const satisfies ReadonlyArray<{ id: GalleryView; icon: typeof Rows3 }>

/** Lives in the gallery column's own toolbar, above the rows it lays out.
 *  Which layout suits a set of outputs changes by the minute — dense to find
 *  something, one-up to judge it — so the choice stays visible rather than
 *  buried in settings. The selected view is sunken and the others are raised,
 *  the same grammar the navigation uses. */
export function GalleryViewSwitcher() {
  const { t } = useTranslation('activity')
  const galleryView = useStore(s => s.galleryView)
  const setGalleryView = useStore(s => s.setGalleryView)

  return (
    <div
      role="group"
      aria-label={t('view.label')}
      className="flex items-center gap-0.5 rounded-lg border border-border/70 bg-bg-secondary p-0.5"
    >
      {VIEWS.map(({ id, icon: Icon }) => {
        const active = galleryView === id
        const label = id === 'feed' ? t('view.feed') : id === 'grid' ? t('view.grid') : t('view.masonry')
        return (
          <button
            key={id}
            type="button"
            onClick={() => setGalleryView(id)}
            aria-pressed={active}
            title={label}
            aria-label={label}
            className={`flex h-10 w-11 items-center justify-center rounded-md transition-colors ${
              active
                ? 'bg-black/30 text-text-primary shadow-[inset_0_1px_3px_rgba(0,0,0,0.55)]'
                : 'text-text-muted hover:bg-white/[0.07] hover:text-text-secondary'
            }`}
          >
            <Icon size={14} />
          </button>
        )
      })}
    </div>
  )
}
