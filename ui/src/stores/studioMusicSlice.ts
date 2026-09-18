import type { AudioSubMode, GenerationMode } from '../types'
import type { SliceCreator } from './storeApi'

export type StudioMusicSlice = {
  musicDescription: string
  setMusicDescription: (s: string) => void
  musicInstrumental: boolean
  setMusicInstrumental: (b: boolean) => void
}

export type StudioMusicSubmitSource = {
  generationMode: GenerationMode
  audioSubMode: AudioSubMode
  musicDescription: string
  musicInstrumental: boolean
  durationSeconds: number
}

/** Song-writer sidecar plus the generation.music submit carriers. */
export function applyStudioMusicSubmitParams(
  params: Record<string, unknown>,
  state: StudioMusicSubmitSource,
): Record<string, unknown> {
  if (state.generationMode !== 'audio' || state.audioSubMode !== 'music') return params
  params._music_description = state.musicDescription || ''
  params._music_instrumental = !!state.musicInstrumental
  params.video_length = 0
  params.image_mode = 0
  params.multi_prompts_gen_type = 2
  params.duration_seconds = state.durationSeconds
  return params
}

/** Restore Music form from a sidecar. Missing description clears; [instrumental] lyrics still mark instrumental. */
export function restoredStudioMusicForm(
  sidecar: Record<string, unknown>,
  restoredLyrics = '',
): Pick<StudioMusicSlice, 'musicDescription' | 'musicInstrumental'> {
  const description = sidecar._music_description
  return {
    musicDescription: typeof description === 'string' ? description : '',
    musicInstrumental: Boolean(sidecar._music_instrumental)
      || restoredLyrics.trim().toLowerCase() === '[instrumental]',
  }
}

export const createStudioMusicSlice: SliceCreator<StudioMusicSlice> = set => ({
  musicDescription: '',
  setMusicDescription: s => set({ musicDescription: s }),
  musicInstrumental: false,
  setMusicInstrumental: b => set({ musicInstrumental: b }),
})
