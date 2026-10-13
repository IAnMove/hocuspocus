import * as api from '../../../api/client'
import type { GenerationPreset } from '../../../api/client'
import type { GenerateParams, GenerationMode } from '../../../types'
import type { SliceCreator } from '../../../stores/storeApi'

export type PresetsSlice = {
  // Presets
  presets: GenerationPreset[]
  presetsLoading: boolean
  loadPresets: () => Promise<void>
  savePreset: (name: string) => Promise<void>
  loadPreset: (preset: GenerationPreset) => void
  deletePreset: (id: string) => Promise<void>
}

export type PresetsSliceHost = PresetsSlice & {
  params: GenerateParams
  loraWeights: Record<string, number[]>
  generationMode: GenerationMode
}

export const createPresetsSlice: SliceCreator<PresetsSlice, PresetsSliceHost> = (set, get) => ({
  // Presets
  presets: [],
  presetsLoading: false,

  loadPresets: async () => {
    set({ presetsLoading: true })
    try {
      const { presets } = await api.fetchPresets()
      set({ presets })
    } catch (e) {
      console.error('Failed to load presets:', e)
    } finally {
      set({ presetsLoading: false })
    }
  },

  savePreset: async (name) => {
    const { params, loraWeights, generationMode } = get()
    try {
      const preset = await api.createPreset({
        name,
        mode: generationMode,
        model_type: params.model_type,
        prompt: '',
        activated_loras: params.activated_loras,
        loras_multipliers: params.loras_multipliers,
        lora_weights: loraWeights,
        params: {
          num_inference_steps: params.num_inference_steps,
          guidance_scale: params.guidance_scale,
          resolution: params.resolution,
          seed: params.seed,
          negative_prompt: params.negative_prompt,
          flow_shift: params.flow_shift,
          h3_audio_shift: params.h3_audio_shift,
          h3_audio_prompt: params.h3_audio_prompt,
          h3_ref_image_size: params.h3_ref_image_size,
          h3_reference_mode: params.h3_reference_mode,
          h3_model_profile: params.h3_model_profile,
          self_refiner_setting: params.self_refiner_setting,
          stage2_steps: params.stage2_steps,
        },
      })
      set(s => ({ presets: [...s.presets, preset] }))
    } catch (e) {
      console.error('Failed to save preset:', e)
    }
  },

  loadPreset: (preset) => {
    const newParams: Partial<GenerateParams> = {
      activated_loras: preset.activated_loras,
      loras_multipliers: preset.loras_multipliers,
      ...(preset.params as Partial<GenerateParams>),
    }
    set(s => ({
      params: { ...s.params, ...newParams },
      loraWeights: preset.lora_weights || {},
    }))
  },

  deletePreset: async (id) => {
    try {
      await api.deletePreset(id)
      set(s => ({ presets: s.presets.filter(p => p.id !== id) }))
    } catch (e) {
      console.error('Failed to delete preset:', e)
    }
  },
})
