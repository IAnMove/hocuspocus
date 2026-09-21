import type { AspectRatio, ResolutionPreset } from '../../types'

export type InspectQueueCommand = { scope: 'active' | 'all' }
export type QueueTaskCommand = { taskId: string; confirm: true }

export type PrepareVideoCommand = {
  prompt: string
  modelType?: string
  durationSeconds?: number
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
  audioDirection?: string
  turbo?: boolean
}

export type PrepareImageCommand = {
  prompt: string
  modelType?: string
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
  outpaintMargins?: string
}

export type PrepareAudioCommand = {
  subMode: 'speech' | 'music' | 'sfx'
  prompt: string
  modelType?: string
  durationSeconds?: number
  negativePrompt?: string
  /** ACE-Step Music Caption (style/genre/instruments), kept literal. */
  altPrompt?: string
  /** Music description is a separate visible Studio field. */
  musicDescription?: string
  musicInstrumental?: boolean
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  /** Music's native command currently admits one output. */
  outputCount?: number
  /** Native MMAudio SFX text-conditioning weight (0..5). */
  sfxTextWeight?: number
  /** Canonical SFX video reference; omitted preserves the selected guide, null removes it. */
  videoGuide?: string | null
}

export type Prepare3dCommand = {
  prompt: string
  modelType?: string
  preset?: string
  seed?: number
}

export type StartGenerationCommand = {
  confirm: true
}

export type AttachStudioReferencesCommand = {
  outputNames: string[]
  role: 'start_frame' | 'subject' | 'style' | 'edit_source' | 'edit_mask'
  replaceExisting: boolean
  removeBackground: boolean
}

export type StudioLoraSelection = {
  name: string
  weight: number
}

export type ConfigureStudioLorasCommand = {
  loras: StudioLoraSelection[]
  replaceExisting: boolean
}

export type QueueSfxClip = {
  name: string
  prompt: string
  durationSeconds: number
}

export type QueueSfxPackCommand = {
  style: string
  clips: QueueSfxClip[]
  modelType?: string
  negativePrompt?: string
  confirm: true
}
