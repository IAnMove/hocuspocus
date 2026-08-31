import { useStore } from '../../stores/useStore'
import type { AgentPrepareAudioAction, AgentQueueSfxPackAction } from './agentActions'
import type { AgentSfxClip } from './sfxPack'

const AUDIO_SUB_MODE_DEFAULTS: Record<AgentPrepareAudioAction['subMode'], string> = {
  speech: 'kugelaudio_0_open',
  music: 'ace_step_v1_5_xl_sft_lm_4b',
  sfx: 'mmaudio_v2',
}

function openStudioAudio(subMode: AgentPrepareAudioAction['subMode']): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarMode('studio')
  state.setSidebarOpen(true)
  state.setGenerationMode('audio')
  state.setAudioSubMode(subMode)
}

async function selectAudioModel(preferred?: string, subMode: AgentPrepareAudioAction['subMode'] = 'sfx'): Promise<string> {
  let state = useStore.getState()
  if (!state.modelsLoaded) await state.loadModels()
  state = useStore.getState()
  const fallback = AUDIO_SUB_MODE_DEFAULTS[subMode]
  const requested = preferred && state.models.some(model => model.model_type === preferred)
    ? preferred
    : state.params.model_type && state.models.some(model => model.model_type === state.params.model_type)
      ? state.params.model_type
      : fallback
  if (requested && state.params.model_type !== requested) {
    state.selectModel(requested)
  }
  const selected = useStore.getState().params.model_type || requested || fallback
  const selectedModel = useStore.getState().models.find(model => model.model_type === selected)
  return selectedModel?.name || selected
}

function applySfxClip(clip: AgentSfxClip, negativePrompt: string): void {
  const state = useStore.getState()
  state.setDurationSeconds(Math.max(1, Math.min(20, clip.durationSeconds)))
  state.setParams({
    prompt: clip.prompt,
    MMAudio_prompt: clip.prompt,
    MMAudio_neg_prompt: negativePrompt || 'music, speech, talking, vocals, long melody',
    video_guide: undefined,
  })
}

export async function prepareAudio(action: AgentPrepareAudioAction): Promise<string> {
  openStudioAudio(action.subMode)
  const modelName = await selectAudioModel(action.modelType, action.subMode)
  const state = useStore.getState()
  if (action.subMode === 'sfx') {
    applySfxClip({
      name: 'sfx',
      prompt: action.prompt,
      durationSeconds: action.durationSeconds ?? 2,
    }, action.negativePrompt || '')
  } else {
    state.setDurationSeconds(action.durationSeconds ?? state.durationSeconds)
    state.setParams({
      prompt: action.prompt,
      negative_prompt: action.negativePrompt || '',
    })
  }
  const duration = useStore.getState().durationSeconds
  const room = action.subMode === 'sfx' ? 'SFX' : action.subMode === 'music' ? 'Music' : 'Speech'
  return `He preparado Studio → Audio → ${room} con ${modelName}, ${duration.toFixed(0)} s y el prompt indicado. La pestaña Audios solo muestra resultados; la creación queda en Studio.`
}

export async function queueMusic(action: AgentPrepareAudioAction): Promise<{ message: string; taskId: string }> {
  if (action.subMode !== 'music') throw new Error('queueMusic solo acepta peticiones de música.')
  await prepareAudio(action)
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
