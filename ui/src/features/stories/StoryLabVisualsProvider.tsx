import type { ReactNode } from 'react'
import { StoryLabVisualsContext, type StoryLabVisuals } from './storyLabVisuals'

export function StoryLabVisualsProvider({
  value,
  children,
}: {
  value: StoryLabVisuals
  children: ReactNode
}) {
  return <StoryLabVisualsContext.Provider value={value}>{children}</StoryLabVisualsContext.Provider>
}
