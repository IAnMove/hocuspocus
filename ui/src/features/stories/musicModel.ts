import type { StoryMusicDraft } from './types'

export const ACE_STEP_MUSIC_MODEL = 'ace_step_v1_5_xl_sft_lm_4b' as const
export const MINIMAX_MUSIC3_LOCAL_MODEL = 'minimax_music3' as const

export type StoryMusicModel = StoryMusicDraft['model']

export interface StoryMusicModelInventoryItem {
  model_type: string
  is_downloaded?: boolean
  enabled?: boolean
  family?: string
}

export function isAceStepMusicModel(model: string | undefined): boolean {
  const value = String(model || '')
  return value.startsWith('ace_step') || value === 'ace-step'
}

export function isLocalMusicModel(model: string | undefined): boolean {
  return isAceStepMusicModel(model) || String(model || '') === MINIMAX_MUSIC3_LOCAL_MODEL
}

export const STORY_MUSIC_DURATION_MIN = 20
export const STORY_MUSIC_DURATION_MAX = 360
export const MINIMAX_MUSIC3_DURATION_MAX = 300

export function storyMusicDurationMax(model: string | undefined): number {
  return String(model || '') === MINIMAX_MUSIC3_LOCAL_MODEL
    ? MINIMAX_MUSIC3_DURATION_MAX
    : STORY_MUSIC_DURATION_MAX
}

export function clampStoryMusicDuration(value: unknown, model?: string): number {
  const numeric = Number(value)
  const seconds = Number.isFinite(numeric) && numeric > 0 ? numeric : 90
  return Math.max(STORY_MUSIC_DURATION_MIN, Math.min(storyMusicDurationMax(model), seconds))
}

export function storyMusicGenerationReady(
  model: string | undefined,
  minimaxConfigured: boolean,
): boolean {
  return isLocalMusicModel(model) || minimaxConfigured
}

export function normalizeStoryMusicModel(model: unknown): StoryMusicDraft['model'] {
  const value = String(model || '')
  if (value === 'music-2.6' || value === 'music-3.0' || value === MINIMAX_MUSIC3_LOCAL_MODEL) return value
  return ACE_STEP_MUSIC_MODEL
}

export function isStoryMusicModel(model: unknown): model is StoryMusicModel {
  return model === ACE_STEP_MUSIC_MODEL
    || model === MINIMAX_MUSIC3_LOCAL_MODEL
    || model === 'music-2.6'
    || model === 'music-3.0'
}

/**
 * Resolve the Wizard's implicit Story song model without guessing from labels.
 * An explicit request always wins. Otherwise a downloaded selected model wins,
 * followed by the only downloaded music model. If there is no unambiguous
 * installed choice, retain the Story selector (or the stable ACE fallback).
 */
export function resolveStoryMusicModel(
  requested: unknown,
  selected: unknown,
  inventory: StoryMusicModelInventoryItem[] = [],
): StoryMusicModel {
  if (isStoryMusicModel(requested)) return requested
  const musicModels = inventory.filter(item => item.family === 'tts' && isStoryMusicModel(item.model_type))
  const installed = musicModels.filter(item => item.is_downloaded === true)
  if (isStoryMusicModel(selected) && installed.some(item => item.model_type === selected)) {
    return selected
  }
  if (installed.length === 1) return installed[0].model_type as StoryMusicModel
  if (isStoryMusicModel(selected)) return selected
  return ACE_STEP_MUSIC_MODEL
}

export function songWriteTarget(model: string | undefined): 'ace-step' | 'minimax' | 'minimax-music3' {
  if (String(model || '') === MINIMAX_MUSIC3_LOCAL_MODEL) return 'minimax-music3'
  return isAceStepMusicModel(model) ? 'ace-step' : 'minimax'
}
