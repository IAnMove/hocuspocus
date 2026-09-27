import { musicVideoShouldUseDirectVideo } from './musicVideoLook'
import type { StoryMusicVideoGenerationMode, StoryProject } from './types'

export function storyVisualGuidanceMode(
  project: Pick<StoryProject, 'projectType' | 'musicVideoGenerationMode' | 'visualStyle' | 'characterVisualStyle'>,
): StoryMusicVideoGenerationMode {
  if (project.projectType === 'music_video' && musicVideoShouldUseDirectVideo(project)) return 'direct_video'
  return project.musicVideoGenerationMode
}

export function storyRecipeRequiresVisualIdentities(mode: StoryMusicVideoGenerationMode): boolean {
  return mode === 'image_guided'
}

export function storyRecipeRequiresApprovedReferences(mode: StoryMusicVideoGenerationMode): boolean {
  return mode === 'direct_references'
}

export function approvedAttachedReferenceCount(project: StoryProject): number {
  const ids = new Set([
    ...project.world.referenceAssetIds,
    ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ...project.characters.flatMap(character => character.referenceAssetIds),
  ])
  return [...ids].filter(id => project.assets[id]?.approval === 'approved').length
}

export function charactersMissingVisualIdentities(project: StoryProject): typeof project.characters {
  return project.characters.filter(character =>
    !character.primaryReferenceAssetId
    || project.assets[character.primaryReferenceAssetId]?.approval !== 'approved')
}

export function assertStoryVisualRecipeReady(project: StoryProject): void {
  const mode = storyVisualGuidanceMode(project)
  if (storyRecipeRequiresVisualIdentities(mode)) {
    const incomplete = charactersMissingVisualIdentities(project)
    if (incomplete.length) {
      const names = incomplete.map(character => character.name || 'Unnamed').join(', ')
      throw new Error(`The start-image recipe needs approved visual identities: ${names}.`)
    }
  }
  if (storyRecipeRequiresApprovedReferences(mode) && approvedAttachedReferenceCount(project) === 0) {
    throw new Error('The direct-reference recipe needs at least one approved attached image.')
  }
}
