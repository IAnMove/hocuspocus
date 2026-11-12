import i18n from '../../i18n'
import { useStore } from '../../stores/useStore'
import type { AgentPrepareAudioAction } from './agentActions'
import { prepareAudio as prepareStudioAudio } from '../studio/actions'

export async function prepareAudio(action: AgentPrepareAudioAction): Promise<string> {
  const result = await prepareStudioAudio(action)
  const summary = result.artifacts[0]?.metadata?.summary
  return typeof summary === 'string' ? summary : i18n.t('wizard:replies.studioAudioReady')
}

export async function queueMusic(action: AgentPrepareAudioAction): Promise<{ message: string; taskId: string }> {
  if (action.subMode !== 'music') throw new Error(i18n.t('wizard:actionErrors.queueMusicMusicOnly'))
  await prepareStudioAudio(action)
  const known = new Set(useStore.getState().jobs)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !known.has(job))
  if (!created?.id) throw new Error(i18n.t('wizard:actionErrors.songMissingTaskId'))
  if (created.status === 'failed') throw new Error(created.error || created.message || i18n.t('wizard:actionErrors.songQueueFailed'))
  return { message: i18n.t('wizard:replies.songQueued', { id: created.id }), taskId: created.id }
}
