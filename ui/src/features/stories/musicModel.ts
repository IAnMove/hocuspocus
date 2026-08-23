import type { StoryMusicDraft } from './types'

export const ACE_STEP_MUSIC_MODEL = 'ace_step_v1_5_xl_sft_lm_4b' as const

export function isAceStepMusicModel(model: string | undefined): boolean {
  const value = String(model || '')
  return value.startsWith('ace_step') || value === 'ace-step'
}

export function normalizeStoryMusicModel(model: unknown): StoryMusicDraft['model'] {
  const value = String(model || '')
  if (value === 'music-2.6' || value === 'music-3.0') return value
  return ACE_STEP_MUSIC_MODEL
}

export function songWriteTarget(model: string | undefined): 'ace-step' | 'minimax' {
  return isAceStepMusicModel(model) ? 'ace-step' : 'minimax'
}
