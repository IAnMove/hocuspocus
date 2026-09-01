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
}

export type PrepareAudioCommand = {
  subMode: 'speech' | 'music' | 'sfx'
  prompt: string
  modelType?: string
  durationSeconds?: number
  negativePrompt?: string
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
  role: 'start_frame' | 'subject' | 'style'
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
