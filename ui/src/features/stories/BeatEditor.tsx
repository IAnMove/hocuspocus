import { ChevronDown, ChevronUp, Clapperboard, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { button, panel, Field } from './storyLabChrome'
import { moveItem } from './storyLabEditors'
import { openStoryBeatScene } from './openBeatScene'
import type { StoryBeat, StoryProject } from './types'

export function BeatEditor({ beat, index, total, update }: {
  beat: StoryBeat
  index: number
  total: number
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const [sceneError, setSceneError] = useState('')
  const set = (patch: Partial<StoryBeat>) => update(current => {
    current.beats = current.beats.map(item => item.id === beat.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} grid md:grid-cols-[60px_1fr_1fr] gap-3`}>
      <div className="space-y-2">
        <div className="text-2xl font-bold text-text-muted/40">{String(index + 1).padStart(2, '0')}</div>
        <div className="flex gap-1">
          <button className={button} disabled={index === 0} title={t('structure.moveUp')} onClick={() => update(current => {
            moveItem(current.beats, index, index - 1)
            return current
          })}><ChevronUp size={12} /></button>
          <button className={button} disabled={index === total - 1} title={t('structure.moveDown')} onClick={() => update(current => {
            moveItem(current.beats, index, index + 1)
            return current
          })}><ChevronDown size={12} /></button>
        </div>
      </div>
      <div className="space-y-3">
        <Field label={t('structure.fields.stage')} value={beat.stage} onChange={stage => set({ stage })} />
        <Field label={t('structure.fields.title')} value={beat.title} onChange={title => set({ title })} />
        <Field label={t('structure.fields.summary')} value={beat.summary} onChange={summary => set({ summary })} rows={4} />
      </div>
      <div className="space-y-3">
        <Field label={t('structure.fields.goal')} value={beat.goal} onChange={goal => set({ goal })} rows={2} />
        <Field label={t('structure.fields.conflict')} value={beat.conflict} onChange={conflict => set({ conflict })} rows={2} />
        <Field label={t('structure.fields.turn')} value={beat.turn} onChange={turn => set({ turn })} rows={3} />
        {beat.sceneLink && (
          <div className="space-y-1">
            <button type="button" className={`${button} w-full border-cyan-400/50 text-cyan-100`}
              data-testid={`open-beat-scene-${beat.id}`}
              onClick={() => {
                setSceneError('')
                void openStoryBeatScene(beat.sceneLink!).catch(error => {
                  setSceneError(error instanceof Error ? error.message : t('structure.sceneOpenFailed'))
                })
              }}>
              <Clapperboard size={12} /> {beat.sceneLink.label || (beat.sceneLink.editor === 'video3d' ? t('structure.openVideo3d') : t('structure.openVideo2d'))}
            </button>
            {sceneError && <p className="text-[10px] text-red-300">{sceneError}</p>}
          </div>
        )}
        <button className="text-red-400 text-xs flex items-center gap-1" onClick={() => update(current => {
          current.beats = current.beats.filter(item => item.id !== beat.id)
          return current
        })}><Trash2 size={12} /> {t('structure.remove')}</button>
      </div>
    </div>
  )
}
