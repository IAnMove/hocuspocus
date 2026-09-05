import { Plus, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, input, panel, Field, SectionHeader, type StoryLabSectionTabProps } from './storyLabChrome'
import { storyId } from './model'
import type { StoryProject, StoryRelationship } from './types'

export function StoryRelationshipsTab({
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
      <div id="story-review-relationships" className="scroll-mt-4">
        <SectionHeader title={t('relationships.title')} description={t('relationships.description')} scope="relationships" busy={busy} approved={isApproved('relationships')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('relationships')} />
      </div>
      <div className="flex justify-end mb-3">
        <button className={button} disabled={project.characters.length < 2} onClick={() => update(current => {
          current.relationships.push({ id: storyId('relationship'), fromCharacterId: current.characters[0]?.id || '', toCharacterId: current.characters[1]?.id || '', label: '', dynamic: '', evolution: '' })
          return current
        })}><Plus size={13} /> {t('relationships.add')}</button>
      </div>
      <div className="space-y-3">
        {project.relationships.map(relationship => (
          <RelationshipEditor key={relationship.id} relationship={relationship} project={project} update={update} />
        ))}
      </div>
    </>
  )
}

function RelationshipEditor({
  relationship, project, update,
}: {
  relationship: StoryRelationship
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const set = (patch: Partial<StoryRelationship>) => update(current => {
    current.relationships = current.relationships.map(item => item.id === relationship.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} grid md:grid-cols-2 gap-3`}>
      <label className="text-[10px] text-text-muted">{t('relationships.from')}
        <select className={`${input} mt-1`} value={relationship.fromCharacterId} onChange={event => set({ fromCharacterId: event.target.value })}>
          {project.characters.map(character => <option key={character.id} value={character.id}>{character.name}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('relationships.to')}
        <select className={`${input} mt-1`} value={relationship.toCharacterId} onChange={event => set({ toCharacterId: event.target.value })}>
          {project.characters.map(character => <option key={character.id} value={character.id}>{character.name}</option>)}
        </select>
      </label>
      <Field label={t('relationships.label')} value={relationship.label} onChange={label => set({ label })} />
      <button className="text-red-400 justify-self-end" onClick={() => update(current => {
        current.relationships = current.relationships.filter(item => item.id !== relationship.id)
        return current
      })}><Trash2 size={14} /></button>
      <Field label={t('relationships.dynamic')} value={relationship.dynamic} onChange={dynamic => set({ dynamic })} rows={3} />
      <Field label={t('relationships.evolution')} value={relationship.evolution} onChange={evolution => set({ evolution })} rows={3} />
    </div>
  )
}
