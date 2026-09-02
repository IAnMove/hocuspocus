import type { StoryAssetSuggestion } from '../../api/stories'

export type PendingSmartAsset = StoryAssetSuggestion & { selected: boolean }

export function storyAssetKey(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}
