/** Pure geometry and prompt helpers for the image "Fondo infinito" workflow.
 *
 * Coordinates are expressed in a three-tile preview canvas. The source image
 * occupies the middle tile, with identical copies on either side. Keeping the
 * coordinate system explicit makes the preview and a later inpaint hand-off
 * use exactly the same seam locations.
 */

export type PanoramaRect = {
  x: number
  y: number
  width: number
  height: number
}

export type PanoramaTile = PanoramaRect & { index: 0 | 1 | 2 }

export type PanoramaLoopLayout = {
  canvas: PanoramaRect
  tiles: PanoramaTile[]
  seamBands: PanoramaRect[]
  seamBandWidth: number
}

export type PanoramaPromptOptions = {
  subject: string
  style?: string
  foregroundOccluder?: string
  extra?: string
}

const positive = (value: number, fallback: number): number =>
  Number.isFinite(value) && value > 0 ? value : fallback

/** Build the canonical 3x canvas used by the preview and seam-aware tools. */
export function createTripleTileLayout(
  width: number,
  height: number,
  seamBandWidth = Math.max(2, width * 0.08),
): PanoramaLoopLayout {
  const tileWidth = positive(width, 1)
  const tileHeight = positive(height, 1)
  const bandWidth = Math.min(tileWidth, positive(seamBandWidth, tileWidth * 0.08))
  const canvas = { x: 0, y: 0, width: tileWidth * 3, height: tileHeight }
  const tiles: PanoramaTile[] = [0, 1, 2].map(index => ({
    index: index as 0 | 1 | 2,
    x: index * tileWidth,
    y: 0,
    width: tileWidth,
    height: tileHeight,
  }))
  const seamBands = [tileWidth, tileWidth * 2].map(x => ({
    x: x - bandWidth / 2,
    y: 0,
    width: bandWidth,
    height: tileHeight,
  }))
  return { canvas, tiles, seamBands, seamBandWidth: bandWidth }
}

/** Return placements suitable for drawing three copies into a preview canvas. */
export function createTripleTilePreviewPlacements(width: number, height: number): PanoramaTile[] {
  return createTripleTileLayout(width, height).tiles
}

/** The two vertical bands that must be checked or repaired for a horizontal loop. */
export function createSeamBandRects(
  width: number,
  height: number,
  seamBandWidth = Math.max(2, width * 0.08),
): PanoramaRect[] {
  return createTripleTileLayout(width, height, seamBandWidth).seamBands
}

/** Build a provider-neutral instruction for making the source tile loopable. */
export function buildInfinitePanoramaPrompt(options: PanoramaPromptOptions): string {
  const subject = options.subject.trim() || 'the supplied environment'
  const style = options.style?.trim()
  const occluder = options.foregroundOccluder?.trim()
  const extra = options.extra?.trim()
  const clauses = [
    `Create a seamless horizontally looping panorama of ${subject}.`,
    'Make the left and right edges continue naturally into each other with matching perspective, lighting, color and texture.',
    'Keep the horizon and camera height stable across the full image; no frame, border, text or visible cut line.',
    style ? `Visual style: ${style}.` : '',
    occluder ? `A natural foreground ${occluder} may cross the join to disguise any remaining seam.` : '',
    extra || '',
  ]
  return clauses.filter(Boolean).join(' ')
}
