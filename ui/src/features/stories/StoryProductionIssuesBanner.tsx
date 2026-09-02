import { ChevronRight, Play } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel } from './storyLabChrome'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryProductionIssuesBanner(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, visibleProductionIssues, onNavigate, onOpenIssue, directMusicVideo,
  } = props
  return (
    <>
      {visibleProductionIssues.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
          <p className="font-medium">{visibleProductionIssues.length === 1 ? t('productions.missingOne') : t('productions.missingMany', { count: visibleProductionIssues.length })}</p>
          <p className="mt-1 text-[10px] leading-relaxed text-amber-200/80">
            {directMusicVideo && project.projectType === 'music_video' ? t('productions.directVideoReviewHint') : t('productions.reviewHint')}
          </p>
          <div className="mt-2 grid gap-1.5 md:grid-cols-2">
            {visibleProductionIssues.map(issue => (
              <button key={issue.id} type="button" onClick={() => onOpenIssue(issue)}
                className="flex items-start gap-2 rounded-md border border-amber-400/25 bg-bg-primary/30 px-2.5 py-2 text-left hover:border-amber-300/60 hover:bg-amber-500/10">
                <ChevronRight size={14} className="mt-0.5 shrink-0" />
                <span>
                  <span className="block font-medium">{issue.label}</span>
                  <span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{issue.detail}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {project.productions.length > 0 && <div className={`${panel} mt-4 flex flex-wrap items-center gap-3`}><div className="mr-auto"><h3 className="text-sm font-semibold text-text-primary">{t('productions.inAssembly', { count: project.productions.length })}</h3><p className="mt-1 text-[10px] text-text-muted">{t('productions.assemblyHint')}</p></div><button className={button} onClick={() => onNavigate('assembly')}><Play size={13} />{t('productions.openAssembly')}</button></div>}
    </>
  )
}
