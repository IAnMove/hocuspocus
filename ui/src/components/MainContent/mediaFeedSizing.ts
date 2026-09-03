const INFO_BAR_HEIGHT = 48
const ASPECT_RATIO = 0.5625

// Leave room for feed padding, the metadata/action bar, and the card border.
// Otherwise a full-width 16:9 preview on an ultrawide window can become taller
// than the feed viewport and push its own metadata below the fold.
const CARD_NON_MEDIA_HEIGHT = 112
const MIN_MEDIA_HEIGHT = 96

export function mediaFeedMaxPreviewHeight(containerHeight: number): number {
  return Math.max(MIN_MEDIA_HEIGHT, Math.floor(containerHeight - CARD_NON_MEDIA_HEIGHT))
}

export function estimatedMediaFeedItemHeight(containerWidth: number, containerHeight: number): number {
  const previewHeight = Math.min(containerWidth * ASPECT_RATIO, mediaFeedMaxPreviewHeight(containerHeight))
  return Math.round(previewHeight) + INFO_BAR_HEIGHT
}
