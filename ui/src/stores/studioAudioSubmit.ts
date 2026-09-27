import { isInstructionSpeechModel, applyInstructionSpeechParams } from '../lib/instructionSpeech'
import { applyStudioMusicSubmitParams, type StudioMusicSubmitSource } from './studioMusicSlice'

export type StudioSpeechVoice = { name?: string | null; path?: string | null }

export type StudioSpeechSubmitSource = {
  generationMode: string
  audioSubMode: string
  durationSeconds: number
  ttsSpeakerName1?: string
  ttsSpeakerName2?: string
  ttsVoiceCount: number
  ttsVoices: ReadonlyArray<StudioSpeechVoice | undefined>
  modelOptions?: {
    audio_only?: boolean
    duration_slider?: { default?: number; max?: number } | null
    default_num_inference_steps?: number | null
  } | null
}

export type StudioAudioSubmitSource = StudioMusicSubmitSource & StudioSpeechSubmitSource

function escapeSpeakerName(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function applyNamedSpeechSpeakers(params: Record<string, unknown>, state: StudioSpeechSubmitSource): void {
  params._tts_speaker_name1 = state.ttsSpeakerName1 || ''
  params._tts_speaker_name2 = state.ttsSpeakerName2 || ''
  for (let i = 0; i < state.ttsVoices.length; i++) {
    params[`_tts_speaker_name${i + 1}`] = state.ttsVoices[i]?.name || ''
  }
  params._tts_voice_count = state.ttsVoiceCount
  let text = String(params.prompt ?? '')
  for (let i = 0; i < state.ttsVoices.length; i++) {
    const name = state.ttsVoices[i]?.name
    if (name) text = text.replace(new RegExp(escapeSpeakerName(name) + '\\s*:', 'gi'), `Speaker ${i + 1}:`)
  }
  params.prompt = text
  for (let i = 0; i < state.ttsVoices.length; i++) {
    const path = state.ttsVoices[i]?.path
    if (path) params[i === 0 ? 'audio_guide' : `audio_guide${i + 1}`] = path
  }
}

function applySpeechTiming(params: Record<string, unknown>, state: StudioSpeechSubmitSource): void {
  if (state.modelOptions?.audio_only) {
    const slider = state.modelOptions.duration_slider
    params.duration_seconds = state.durationSeconds === 0
      ? (slider?.default ?? slider?.max ?? 600)
      : state.durationSeconds
  }
  if ((params.num_inference_steps as number) > 0 && state.modelOptions?.default_num_inference_steps == null) {
    params.num_inference_steps = 0
  }
  delete params.sliding_window_size
  delete params.sliding_window_overlap
  delete params.sliding_window_discard_last_frames
}

export function applyStudioSfxSubmitParams(
  params: Record<string, unknown>,
  state: { generationMode: string; audioSubMode: string; durationSeconds: number },
): Record<string, unknown> {
  if (state.generationMode !== 'audio' || state.audioSubMode !== 'sfx') return params
  const sfxModel = params.model_type as string
  params.MMAudio_setting = 1
  params._mmaudio_variant = sfxModel === 'mmaudio_nsfw' ? 'nsfw' : 'v2'
  params.prompt = typeof params.MMAudio_prompt === 'string' ? params.MMAudio_prompt : ''
  params.sfx_mode = true
  params.duration_seconds = state.durationSeconds
  params.video_length = 0
  params.num_inference_steps = 25
  params.image_mode = 0
  return params
}

export function applyStudioSpeechSubmitParams(
  params: Record<string, unknown>,
  state: StudioSpeechSubmitSource,
): Record<string, unknown> {
  if (state.generationMode !== 'audio' || state.audioSubMode !== 'speech') return params
  params.video_length = 0
  params.image_mode = 0
  params.multi_prompts_gen_type = 2
  params._tts_original_prompt = params.prompt
  if (isInstructionSpeechModel(params.model_type)) applyInstructionSpeechParams(params)
  else applyNamedSpeechSpeakers(params, state)
  applySpeechTiming(params, state)
  return params
}

export function applyStudioAudioSubmitParams(
  params: Record<string, unknown>,
  state: StudioAudioSubmitSource,
): Record<string, unknown> {
  if (state.generationMode !== 'audio') return params
  params._audio_sub_mode = state.audioSubMode
  applyStudioMusicSubmitParams(params, state)
  applyStudioSfxSubmitParams(params, state)
  applyStudioSpeechSubmitParams(params, state)
  return params
}
