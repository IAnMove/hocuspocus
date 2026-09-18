import type { AppState } from '../../stores/useStore'
import type { AudioSubMode } from '../../types'
import { restoreWan1300AudioRecipe } from '../../lib/wan1300Audio'

const referenceKeys = [
  'audio_prompt_type', 'audio_source',
  'audio_guide', 'audio_guide2', 'audio_guide3', 'audio_guide4', 'audio_guide5', 'audio_guide6',
  // SFX video replacement is a per-tab reference. Leaving it in the shared
  // form after SFX → Speech/Music blocks those commands (active residual /
  // catalog enum) or silently reconditions a later text-only SFX submit.
  'video_guide',
  '_tts_original_prompt', '_tts_voice_count',
  '_tts_speaker_name1', '_tts_speaker_name2', '_tts_speaker_name3',
  '_tts_speaker_name4', '_tts_speaker_name5', '_tts_speaker_name6',
] as const

type VoiceState = Pick<AppState,
  'ttsVoices' | 'ttsVoiceCount' | 'ttsSpeakerName1' | 'ttsSpeakerName2' | 'ttsSpeakerNamesManual'>

export interface AudioReferenceSnapshot {
  params: Record<string, unknown>
  audioGuideFilename: string | null
  audioGuide2Filename: string | null
  speech?: VoiceState
}

export type AudioReferenceStash = Partial<Record<AudioSubMode, AudioReferenceSnapshot>>

export function audioReferenceParams(
  params: Partial<Record<(typeof referenceKeys)[number], unknown>>,
): Record<string, unknown> {
  return Object.fromEntries(referenceKeys.map(key => [key, params[key]]))
}

/** Capture references at their owning tab, before a switch or sidecar restore. */
export function captureAudioReferences(state: AppState): AudioReferenceSnapshot {
  return {
    params: {
      ...audioReferenceParams(state.params),
      // Native YuE2/AuK sampling is not a reference, but the same tab stash is
      // the only place a Speech ↔ Music return can recover it after
      // loadModelOptions resets leftovers.
      ...restoreWan1300AudioRecipe(state.params.model_type, state.params),
    },
    audioGuideFilename: state.audioGuideFilename,
    audioGuide2Filename: state.audioGuide2Filename,
    ...(state.audioSubMode === 'speech' ? { speech: {
      ttsVoices: state.ttsVoices.map(voice => ({ ...voice })),
      ttsVoiceCount: state.ttsVoiceCount,
      ttsSpeakerName1: state.ttsSpeakerName1,
      ttsSpeakerName2: state.ttsSpeakerName2,
      ttsSpeakerNamesManual: state.ttsSpeakerNamesManual,
    } } : {}),
  }
}

/** Mixer has no generation form and must not take ownership of another tab's refs. */
export function stashAudioReferences(state: AppState): AudioReferenceStash {
  if (state.audioSubMode === 'mixer') return state.audioReferenceStash
  return { ...state.audioReferenceStash, [state.audioSubMode]: captureAudioReferences(state) }
}

export function restoreAudioReferences(
  state: AppState, mode: AudioSubMode, stash: AudioReferenceStash,
): Partial<AppState> {
  if (mode === 'mixer') return {}
  const saved = stash[mode]
  const references = saved?.params ?? {
    ...Object.fromEntries(referenceKeys.map(key => [key, undefined])),
    audio_prompt_type: '',
  }
  return {
    params: { ...state.params, ...references },
    audioGuideFilename: saved?.audioGuideFilename ?? null,
    audioGuide2Filename: saved?.audioGuide2Filename ?? null,
    ...(saved?.speech ?? {}),
  }
}
