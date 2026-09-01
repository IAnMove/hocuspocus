import { useStore } from '../../stores/useStore'
import type { AgentPrepareAudioAction, AgentQueueSfxPackAction } from './agentActions'
import { applySfxClip, openStudioAudio, prepareAudio as prepareStudioAudio, selectAudioModel } from '../studio/actions'

export async function prepareAudio(action: AgentPrepareAudioAction): Promise<string> {
  const result = await prepareStudioAudio(action)
  const summary = result.artifacts[0]?.metadata?.summary
  return typeof summary === 'string' ? summary : 'Studio → Audio listo.'
}

export async function queueMusic(action: AgentPrepareAudioAction): Promise<{ message: string; taskId: string }> {
  if (action.subMode !== 'music') throw new Error('queueMusic solo acepta peticiones de música.')
  await prepareStudioAudio(action)
  const known = new Set(useStore.getState().jobs)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !known.has(job))
  if (!created?.id) throw new Error('HocusPocus no devolvió el taskId canónico de la canción.')
  if (created.status === 'failed') throw new Error(created.error || created.message || 'La canción no pudo entrar en cola.')
  return { message: `He enviado la canción a la cola (${created.id}).`, taskId: created.id }
}

export async function queueSfxPack(action: AgentQueueSfxPackAction): Promise<string> {
  if (!action.confirm) throw new Error('Encolar el pack de SFX requiere confirm=true tras una petición explícita.')
  if (!action.clips.length) throw new Error('El pack de SFX no incluye clips.')
  openStudioAudio('sfx')
  await selectAudioModel(action.modelType, 'sfx')
  const ids: string[] = []
  const negative = action.negativePrompt || 'music, speech, talking, vocals, long melody'
  for (const clip of action.clips) {
    applySfxClip(clip, negative)
    const before = new Set(useStore.getState().jobs)
    await useStore.getState().startGeneration()
    const created = useStore.getState().jobs.find(job => !before.has(job))
    if (!created) throw new Error(`HocusPocus no encoló el efecto ${clip.name}.`)
    if (created.status === 'failed') throw new Error(created.error || created.message || `Falló ${clip.name}.`)
    ids.push(`${clip.name}${created.id ? ` (${created.id})` : ''}`)
  }
  return [
    `He encolado **${ids.length} efectos SFX** en Studio → Audio → SFX.`,
    'Irán detrás de lo que ya use la GPU y aparecerán en la galería Audios al terminar.',
    '',
    ...ids.map(id => `- ${id}`),
  ].join('\n')
}
