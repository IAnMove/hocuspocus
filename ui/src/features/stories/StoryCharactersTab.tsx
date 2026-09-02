import { Plus } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, SectionHeader, type StoryLabSectionTabProps } from './storyLabChrome'
import { emptyCharacter } from './storyLabEditors'
import { CharacterEditor } from './CharacterEditor'

export function StoryCharactersTab({
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
      <div id="story-review-characters" className="scroll-mt-4">
        <SectionHeader title={t('characters.title')} description={t('characters.description')} scope="characters" busy={busy} approved={isApproved('characters')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('characters')} />
      </div>
      <div className="flex justify-end mb-3">
        <button className={button} onClick={() => update(current => {
          current.characters.push(emptyCharacter(t('characters.newName')))
          return current
        })}><Plus size={13} /> {t('characters.add')}</button>
      </div>
      <div className="space-y-4">
        {project.characters.map((character, index) => (
          <CharacterEditor key={character.id} character={character} index={index} total={project.characters.length} project={project} update={update} />
        ))}
        {!project.characters.length && <div className={`${panel} text-sm text-text-muted text-center py-12`}>{t('characters.empty')}</div>}
      </div>
    </>
  )
}
