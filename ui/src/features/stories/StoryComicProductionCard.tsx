import { BookOpen, ChevronRight, Sparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel } from './storyLabChrome'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryComicProductionCard(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, comicDirection, setComicDirection, comicPageCount, setComicPageCount,
    comicPanelsPerPage, setComicPanelsPerPage, stageComic, productionIssues,
  } = props
  return (
    <div className={`${panel} space-y-3`}>
      <BookOpen size={26} className="text-accent-blue" />
      <h3 className="font-semibold text-text-primary">{t('productions.comicTitle')}</h3>
      <p className="text-xs text-text-muted">{t('productions.comicHint')}</p>
      <textarea className={input} rows={4} value={comicDirection} onChange={event => setComicDirection(event.target.value)} aria-label={t('productions.comicDirectionAria')} />
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[10px] text-text-muted">{t('productions.pages')}
          <input className={`${input} mt-1`} type="number" min={1} max={100} value={comicPageCount}
            onChange={event => setComicPageCount(Math.max(1, Math.min(100, Number(event.target.value) || 1)))} />
        </label>
        <label className="block text-[10px] text-text-muted">{t('productions.panelsPerPage')}
          <input className={`${input} mt-1`} type="number" min={1} max={12} value={comicPanelsPerPage}
            onChange={event => setComicPanelsPerPage(Math.max(1, Math.min(12, Number(event.target.value) || 1)))} />
        </label>
      </div>
      <div className="flex flex-wrap gap-1">
        {[4, 12, 24].map(count => (
          <button key={count} type="button" className={`${button} ${comicPageCount === count ? 'border-accent-blue text-accent-blue' : ''}`}
            onClick={() => setComicPageCount(count)}>
            {count === 4 ? t('productions.quickTest') : t('productions.pagesCount', { count })}
          </button>
        ))}
      </div>
      <p className="text-[9px] text-text-muted">{t('productions.plannedSize', { count: comicPageCount * comicPanelsPerPage })}</p>
      <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(true)}><Sparkles size={13} /> {t('productions.generateComic')}</button>
      <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(false)}><ChevronRight size={13} /> {t('productions.openComicDirector')}</button>
      <p className="text-[9px] text-text-muted">{t('productions.comicCompleteHint')}</p>
    </div>
  )
}
