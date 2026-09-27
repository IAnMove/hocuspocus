import { useStore } from '../../stores/useStore'
import type { AgentPrepareAudioAction } from './agentActions'
import { prepareAudio as prepareStudioAudio } from '../studio/actions'

export async function prepareAudio(action: AgentPrepareAudioAction): Promise<string> {
  const result = await prepareStudioAudio(action)
  const summary = result.artifacts[0]?.metadata?.summary
  return typeof summary === 'string' ? summary : 'Studio → Audio ready.'
}

export async function queueMusic(action: AgentPrepareAudioAction): Promise<{ message: string; taskId: string }> {
  if (action.subMode !== 'music') throw new Error('queueMusic only accepts music requests.')
  await prepareStudioAudio(action)
  const known = new Set(useStore.getState().jobs)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !known.has(job))
  if (!created?.id) throw new Error('HocusPocus did not return the song\'s canonical taskId.')
  if (created.status === 'failed') throw new Error(created.error || created.message || 'The song could not be queued.')
  return { message: `I sent the song to the queue (${created.id}).`, taskId: created.id }
}
