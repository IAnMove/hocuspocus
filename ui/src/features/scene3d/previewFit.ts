/** Largest picture of the scene ratio that fits the free box. */
export function fittedPicture(
  freeWidth: number,
  freeHeight: number,
  pictureWidth: number,
  pictureHeight: number,
): { width: number; height: number } {
  const ratio = Math.max(1, pictureWidth) / Math.max(1, pictureHeight)
  const width = Math.min(Math.max(0, freeWidth), Math.max(0, freeHeight) * ratio)
  return { width, height: width / ratio }
}
