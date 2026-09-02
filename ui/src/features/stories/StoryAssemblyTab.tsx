import { useUiTranslation } from '../../i18n'
import { button, panel } from './storyLabChrome'
import { StoryProductionTimeline } from './StoryProductionTimeline'
import type { StoryProject } from './types'

export function StoryAssemblyTab({
  project, reopenProduction, restoreProductionSource,
}: {
  project: StoryProject
  reopenProduction: (id: string) => void
  restoreProductionSource: (id: string) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const productions = [...project.productions].reverse()
  return (
    <div className={panel}>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-text-primary">{t('assembly.title')}</h2>
        <p className="mt-1 text-xs text-text-muted">{t('assembly.description')}</p>
      </div>
      {productions.length ? productions.map((item, index) => (
        <div key={item.id} className="border-b border-border py-3 text-xs last:border-0">
          <div className="flex flex-col justify-between gap-2 lg:flex-row lg:items-center">
            <div>
              <span className="text-text-primary capitalize">
                {item.kind === 'music_video' ? t('assembly.musicVideo') : item.kind} · {item.targetName || item.title}
              </span>
              <span className="ml-2 text-text-muted">
                {t('assembly.sourceMeta', { version: item.sourceVersion, when: new Date(item.createdAt).toLocaleString() })}
              </span>
              {item.sourceSnapshot?.sectionVersions
                && JSON.stringify(item.sourceSnapshot.sectionVersions) !== JSON.stringify(project.sectionVersions) && (
                <span className="ml-2 text-amber-300">{t('assembly.sourceChanged')}</span>
              )}
            </div>
            <div className="flex gap-2">
              <button className={button} onClick={() => reopenProduction(item.id)}>{t('assembly.reopen')}</button>
              {item.sourceSnapshot && (
                <button className={button} onClick={() => restoreProductionSource(item.id)}>{t('assembly.restore')}</button>
              )}
            </div>
          </div>
          <StoryProductionTimeline production={item} initiallyOpen={index === 0} />
        </div>
      )) : <p className="text-xs text-text-muted">{t('assembly.empty')}</p>}
    </div>
  )
}
