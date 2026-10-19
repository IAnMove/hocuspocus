import type { ModelDef } from '../types'

/** Speech defaults to VoxCPM2 once its weights are installed; otherwise KugelAudio, the previous default. */
export const PREFERRED_SPEECH_MODEL = 'voxcpm2_voicedesign'
export const FALLBACK_SPEECH_MODEL = 'kugelaudio_0_open'

/** Newer models that become the default for a mode as soon as their weights are installed, in order of preference.
 *  Without any of them the mode keeps its existing default, so a small install is never pointed at a model it cannot run.
 *  Images prefer Qwen Image 2.1 Turbo; an install that has only the base Qwen Image 2.1 keeps it. */
export const PREFERRED_IMAGE_MODEL = 'qwen_image_21_turbo'
export const INSTALLED_FIRST_DEFAULTS: Readonly<Record<string, readonly string[]>> = {
  image: [PREFERRED_IMAGE_MODEL, 'qwen_image_21'],
  audio: [PREFERRED_SPEECH_MODEL],
}

export function installedPreferredModel(
  mode: string,
  models: ReadonlyArray<Pick<ModelDef, 'model_type' | 'is_downloaded'>>,
): string | null {
  const installed = (id: string) => models.some(model => model.model_type === id && model.is_downloaded === true)
  return (INSTALLED_FIRST_DEFAULTS[mode] ?? []).find(installed) ?? null
}

/** The speech model used when nobody picked one: VoxCPM2 when installed, else the fallback. */
export function defaultSpeechModel(models: ReadonlyArray<Pick<ModelDef, 'model_type' | 'is_downloaded'>>): string {
  return installedPreferredModel('audio', models) ?? FALLBACK_SPEECH_MODEL
}
