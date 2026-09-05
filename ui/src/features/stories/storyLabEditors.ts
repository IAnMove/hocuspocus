import { storyId } from './model'
import type { StoryCharacter, StoryProject } from './types'

export function moveItem<T>(items: T[], from: number, to: number): void {
  if (from < 0 || to < 0 || from >= items.length || to >= items.length || from === to) return
  const [item] = items.splice(from, 1)
  items.splice(to, 0, item)
}

export function pruneUnusedAssets(project: StoryProject): void {
  const used = new Set([
    ...project.world.referenceAssetIds,
    ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ...project.characters.flatMap(character => character.referenceAssetIds),
  ])
  Object.keys(project.assets).forEach(id => {
    if (!used.has(id)) delete project.assets[id]
  })
}

export function emptyCharacter(name = 'New character'): StoryCharacter {
  return {
    id: storyId('character'), name, role: '', age: '', pronouns: '',
    personality: '', desire: '', need: '', flaw: '', conflict: '', arc: '', voice: '',
    appearance: '', wardrobe: '', visualPrompt: '', negativePrompt: '',
    referenceAssetIds: [], approval: 'draft',
  }
}
