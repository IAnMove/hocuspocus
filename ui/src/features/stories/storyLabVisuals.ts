import { createContext, useContext } from 'react'

export type StoryVisualKind = 'world' | 'character' | 'location'
export type StoryVisualTarget = { kind: StoryVisualKind; id?: string }

export type StoryLabVisuals = {
  imageBusy: string
  referenceBatchBusy: boolean
  generateVisual: (target: StoryVisualTarget, prompt: string) => void | Promise<unknown>
  requestUpload: (target: StoryVisualTarget) => void
  removeReference: (target: StoryVisualKind, targetId: string | undefined, assetId: string) => void
}

export const StoryLabVisualsContext = createContext<StoryLabVisuals | null>(null)

export function useStoryLabVisuals(): StoryLabVisuals {
  const value = useContext(StoryLabVisualsContext)
  if (!value) {
    throw new Error('useStoryLabVisuals must be used within StoryLabVisualsProvider')
  }
  return value
}
