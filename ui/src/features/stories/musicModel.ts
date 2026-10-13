// The i18next instance src/i18n initializes at app start. Importing src/i18n here
// would pull its locale JSON into stories/model.ts, which E2E specs load in Node.
import i18n from 'i18next'
import { isPaidMinimaxMusicModel } from '../../lib/musicGenerationSpec'
import type { StoryMusicDraft } from './types'

export const ACE_STEP_MUSIC_MODEL = 'ace_step_v1_5_xl_sft_lm_4b' as const
export const MINIMAX_MUSIC3_LOCAL_MODEL = 'minimax_music3' as const
/** Local, free Story music models; the first is the default, as in Studio and production.*. */
export const LOCAL_STORY_MUSIC_MODELS = [ACE_STEP_MUSIC_MODEL, MINIMAX_MUSIC3_LOCAL_MODEL] as const

export type StoryMusicModel = StoryMusicDraft['model']
export type LocalStoryMusicModel = typeof LOCAL_STORY_MUSIC_MODELS[number]
export type PaidStoryMusicModel = Exclude<StoryMusicModel, LocalStoryMusicModel>

export class MusicModelResolutionError extends Error {
  readonly reasons: string[]

  constructor(message: string, reasons: string[] = []) {
    super(message)
    this.name = 'MusicModelResolutionError'
    this.reasons = reasons
  }
}

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

export function storyMusicReadyMessageKey(
  model: string | undefined,
  minimaxConfigured: boolean,
): 'music.aceLocalReady' | 'music.minimaxLocalReady' | 'music.minimaxReady' | 'music.minimaxMissing' {
  if (isAceStepMusicModel(model)) return 'music.aceLocalReady'
  if (String(model || '') === MINIMAX_MUSIC3_LOCAL_MODEL) return 'music.minimaxLocalReady'
  return minimaxConfigured ? 'music.minimaxReady' : 'music.minimaxMissing'
}

export function isPaidStoryMusicModel(model: unknown): model is PaidStoryMusicModel {
  return model === 'music-3.0' || model === 'music-2.6'
}

export function isLocalStoryMusicModel(model: unknown): model is LocalStoryMusicModel {
  return model === ACE_STEP_MUSIC_MODEL || model === MINIMAX_MUSIC3_LOCAL_MODEL
}

/** What an agent gets when it asks for paid MiniMax music: a refusal, never a provider call. */
export function paidMusicDisabledError(model: string): Error {
  return new Error(i18n.t('paidMusicDisabled', {
    ns: 'wizard', model, local: LOCAL_STORY_MUSIC_MODELS.join(', '),
  }))
}

/**
 * A saved paid MiniMax id stays only when a person picked it in the Story Lab
 * selector (`paidModelChosen`). Older saves carried `music-3.0` as a default;
 * they read as "no model", which is the local default.
 */
export function normalizeStoryMusicModel(model: unknown, paidModelChosen = false): StoryMusicDraft['model'] {
  const value = String(model || '')
  if (isPaidStoryMusicModel(value)) return paidModelChosen ? value : ACE_STEP_MUSIC_MODEL
  if (value === MINIMAX_MUSIC3_LOCAL_MODEL) return value
  return ACE_STEP_MUSIC_MODEL
}

type StoryMusicChoice = Pick<StoryMusicDraft, 'model' | 'paidModelChosen' | 'replacedPaidModel'>

/** Read a saved music section: an unchosen paid id becomes the local default and is remembered for a notice. */
export function normalizeStoryMusicChoice(music: unknown): StoryMusicChoice {
  const raw = music && typeof music === 'object' ? music as Record<string, unknown> : {}
  const chosen = raw.paidModelChosen === true && isPaidStoryMusicModel(raw.model)
  const model = normalizeStoryMusicModel(raw.model, chosen)
  const previous = isPaidStoryMusicModel(raw.replacedPaidModel) ? raw.replacedPaidModel : undefined
  const replaced = isPaidStoryMusicModel(raw.model) ? (chosen ? undefined : raw.model) : previous
  return {
    model,
    ...(chosen ? { paidModelChosen: true } : {}),
    ...(replaced ? { replacedPaidModel: replaced } : {}),
  }
}

/** A person's pick in the Story Lab selector: a paid id stays because they chose it. */
export function storyMusicSelection(value: unknown): StoryMusicChoice {
  return {
    model: normalizeStoryMusicModel(value, true),
    paidModelChosen: isPaidStoryMusicModel(value) ? true : undefined,
    replacedPaidModel: undefined,
  }
}

/**
 * Resolve the Wizard's implicit Story song model without guessing from labels.
 * The Wizard never runs paid music: a paid request is refused and a saved paid
 * selection counts as no selection. An explicit local request wins. Otherwise
 * a downloaded selected model wins, followed by the only downloaded music
 * model. If there is no unambiguous installed choice, retain the selector.
 */
export function resolveStoryMusicModel(
  requested: unknown,
  selected: unknown,
  inventory: StoryMusicModelInventoryItem[] = [],
): LocalStoryMusicModel {
  if (isPaidMinimaxMusicModel(requested)) throw paidMusicDisabledError(String(requested))
  if (isLocalStoryMusicModel(requested)) return requested
  const musicModels = inventory.filter(item => item.family === 'tts' && isLocalStoryMusicModel(item.model_type))
  const installed = musicModels.filter(item => item.is_downloaded === true)
  if (isLocalStoryMusicModel(selected) && installed.some(item => item.model_type === selected)) {
    return selected
  }
  if (installed.length === 1) return installed[0].model_type as LocalStoryMusicModel
  if (isLocalStoryMusicModel(selected)) return selected
  throw new MusicModelResolutionError(
    'No music model was requested, selected, or installed.',
    ['Silent ACE-Step fallback is not allowed.'],
  )
}

export function songWriteTarget(model: string | undefined): 'ace-step' | 'minimax' | 'minimax-music3' {
  if (String(model || '') === MINIMAX_MUSIC3_LOCAL_MODEL) return 'minimax-music3'
  return isAceStepMusicModel(model) ? 'ace-step' : 'minimax'
}
