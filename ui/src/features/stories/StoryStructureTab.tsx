import { Plus } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, SectionHeader, type StoryLabSectionTabProps } from './storyLabChrome'
import { BeatEditor } from './BeatEditor'
import { storyId } from './model'

export function StoryStructureTab({
  project,
  update,
  busy,
  instruction,
  setInstruction,
  generate,
  approve,
  isApproved,
}: StoryLabSectionTabProps) {
  const { t } = useUiTranslation('storyLab')
  return (
    <>
      <div id="story-review-structure" className="scroll-mt-4">
        <SectionHeader title={t('structure.title')} description={t('structure.description')} scope="structure" busy={busy} approved={isApproved('structure')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('structure')} />
      </div>
      <div className="flex justify-end mb-3">
        <button className={button} onClick={() => update(current => {
          current.beats.push({ id: storyId('beat'), stage: t('structure.newStage'), title: '', summary: '', goal: '', conflict: '', turn: '' })
          return current
        })}><Plus size={13} /> {t('structure.add')}</button>
      </div>
      <div className="space-y-3">
        {project.beats.map((beat, index) => <BeatEditor key={beat.id} beat={beat} index={index} total={project.beats.length} update={update} />)}
      </div>
    </>
  )
}
