/** AuK consumes the complete instruction and one source, without speaker rewriting. */
export function isInstructionSpeechModel(model: unknown): boolean {
  return model === 'auk' || model === 'auk_flash'
}

export function applyInstructionSpeechParams(params: Record<string, unknown>): void {
  params._tts_voice_count = 0
  for (let index = 1; index <= 6; index++) {
    params[`_tts_speaker_name${index}`] = ''
    if (index > 1) delete params[`audio_guide${index}`]
  }
  // Inactive controls may remain in the shared form after switching models.
  for (const key of ['temperature', 'top_k', 'top_p', 'pause_seconds', 'model_mode', 'custom_settings']) {
    delete params[key]
  }
  params.guidance_phases = params.model_type === 'auk_flash' ? 0 : 1
  if (params.model_type === 'auk_flash') {
    params.num_inference_steps = 4
    params.guidance_scale = 0
  }
}
