// Reserve both the summary and a single horizontally scrollable action row.
const INFO_BAR_HEIGHT = 104
/** CSS width/height used to reserve still space before decode. */
export const MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO = 16 / 9
const ASPECT_RATIO = 1 / MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO

// Leave room for feed padding, the metadata/action bar, and the card border.
// Otherwise a full-width 16:9 preview on an ultrawide window can become taller
// than the feed viewport and push its own metadata below the fold.
const CARD_NON_MEDIA_HEIGHT = INFO_BAR_HEIGHT + 32
const MIN_MEDIA_HEIGHT = 96

export function mediaFeedStillAspectRatio(naturalWidth?: number, naturalHeight?: number): number {
  if (naturalWidth && naturalHeight && naturalWidth > 0 && naturalHeight > 0) {
    return naturalWidth / naturalHeight
  }
  return MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO
}

/** Info-bar-only height the virtualizer must never persist as a card size. */
export function isCollapsedMediaFeedMeasurement(height: number): boolean {
  return !Number.isFinite(height) || height < MIN_MEDIA_HEIGHT
}

export function mediaFeedMaxPreviewHeight(containerHeight: number): number {
  return Math.max(MIN_MEDIA_HEIGHT, Math.floor(containerHeight - CARD_NON_MEDIA_HEIGHT))
}

export function estimatedMediaFeedItemHeight(containerWidth: number, containerHeight: number): number {
  const previewHeight = Math.min(containerWidth * ASPECT_RATIO, mediaFeedMaxPreviewHeight(containerHeight))
  return Math.round(previewHeight) + INFO_BAR_HEIGHT
}
