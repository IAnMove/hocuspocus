export type ImageStudioIntent = 'chooser' | 'new' | 'edit' | 'loop' | 'character'

export const IMAGE_STUDIO_INTENTS: Array<{
  id: Exclude<ImageStudioIntent, 'chooser'>
  icon: string
}> = [
  { id: 'new', icon: '✦' },
  { id: 'edit', icon: '✎' },
  { id: 'character', icon: '☺' },
  { id: 'loop', icon: '∞' },
]
