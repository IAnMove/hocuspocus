import type { GenerateParams } from '../types'

const RECIPES: Record<string, Record<string, number>> = {
  yue2: { model_mode: 0, top_k: 100, top_p: 0.95, temperature: 1,
    num_inference_steps: 32, guidance_scale: 1, guidance_phases: 1 },
  auk: { num_inference_steps: 32, guidance_scale: 2, guidance_phases: 1 },
  auk_flash: { num_inference_steps: 4, guidance_scale: 0, guidance_phases: 0 },
}

/** Saved native audio settings win over the defaults loaded with model options. */
export function restoreWan1300AudioRecipe(model: string, saved: Record<string, unknown>): Partial<GenerateParams> {
  const defaults = RECIPES[model]
  if (!defaults) return {}
  if (model === 'auk_flash') return { ...defaults }
  return Object.fromEntries(Object.entries(defaults).map(([key, fallback]) => [key, saved[key] ?? fallback]))
}

/** Explicit model selection clears references; a tab return already restored its own stash. */
export function wan1300AudioSelection(model: string, preserveReferences = false): {
  params?: Partial<GenerateParams> & Record<string, unknown>; audioGuideFilename?: null; audioGuide2Filename?: null; ttsVoiceCount?: number
} {
  if (!RECIPES[model] || preserveReferences) return {}
  return { audioGuideFilename: null, audioGuide2Filename: null, ttsVoiceCount: 0, params: {
    audio_prompt_type: '', audio_guide: undefined, audio_guide2: undefined,
    audio_guide3: undefined, audio_guide4: undefined, audio_guide5: undefined, audio_guide6: undefined,
  } }
}
