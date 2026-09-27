import type { CharacterKitAsset } from './characterKit'

/** Draft rendering may use saved pending assets without changing their review state. */
export type CharacterKitReviewPolicy = 'approved' | 'saved-draft'

export function usableCharacterAsset(asset: CharacterKitAsset | undefined, policy: CharacterKitReviewPolicy) {
  return Boolean(asset?.source.trim() && (asset.reviewState === 'approved'
    || (policy === 'saved-draft' && asset.reviewState === 'pending')))
}
