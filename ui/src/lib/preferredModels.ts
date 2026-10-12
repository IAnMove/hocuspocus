import type { ModelDef } from '../types'

/** Speech defaults to VoxCPM2 once its weights are installed; otherwise KugelAudio, the previous default. */
export const PREFERRED_SPEECH_MODEL = 'voxcpm2_voicedesign'
export const FALLBACK_SPEECH_MODEL = 'kugelaudio_0_open'

/** Newer models that become the default for a mode as soon as their weights are installed.
 *  Without them the mode keeps its existing default, so a small install is never pointed at a model it cannot run. */
export const INSTALLED_FIRST_DEFAULTS: Readonly<Record<string, string>> = {
  image: 'qwen_image_21',
  audio: PREFERRED_SPEECH_MODEL,
}

export function installedPreferredModel(
  mode: string,
  models: ReadonlyArray<Pick<ModelDef, 'model_type' | 'is_downloaded'>>,
): string | null {
  const preferred = INSTALLED_FIRST_DEFAULTS[mode]
  if (!preferred) return null
  return models.some(model => model.model_type === preferred && model.is_downloaded === true) ? preferred : null
}

/** The speech model used when nobody picked one: VoxCPM2 when installed, else the fallback. */
export function defaultSpeechModel(models: ReadonlyArray<Pick<ModelDef, 'model_type' | 'is_downloaded'>>): string {
  return installedPreferredModel('audio', models) ?? FALLBACK_SPEECH_MODEL
}
