import { useStore } from '../../stores/useStore'
import type { AgentPrepareAudioAction } from './agentActions'
import { prepareAudio as prepareStudioAudio } from '../studio/actions'

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
