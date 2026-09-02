import { useUiTranslation } from '../../i18n'
import { StoryComicProductionCard } from './StoryComicProductionCard'
import { StoryFilmProductionCard } from './StoryFilmProductionCard'
import { StoryProductionIssuesBanner } from './StoryProductionIssuesBanner'
import { StoryProductionsMusicPanel } from './StoryProductionsMusicPanel'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryProductionsTab(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const { project } = props
  const title = project.projectType === 'music_video'
    ? t('productions.titleVideo')
    : project.projectType === 'quick_video'
      ? t('productions.titleQuick')
      : t('productions.title')
  const description = project.projectType === 'full_story' ? t('productions.descriptionStory') : t('productions.descriptionOther')
  return (
    <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        <p className="text-xs text-text-muted mt-1">{description}</p>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {project.projectType === 'full_story' && <StoryComicProductionCard {...props} />}
        {project.projectType !== 'music_video' && <StoryFilmProductionCard {...props} />}
        {project.projectType !== 'quick_video' && <StoryProductionsMusicPanel {...props} />}
      </div>
      <StoryProductionIssuesBanner {...props} />
    </>
  )
}
