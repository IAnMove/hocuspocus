import type { ClipFit, EditorClip } from './editorClipNormalization'

type FrameKnobs = Pick<EditorClip, 'fit' | 'focusX' | 'focusY' | 'blurAmount' | 'backgroundDim'>

export function montageFrameFields(clip: FrameKnobs): FrameKnobs {
  const fields: FrameKnobs = { fit: clip.fit }
  if (clip.focusX !== undefined) fields.focusX = clip.focusX
  if (clip.focusY !== undefined) fields.focusY = clip.focusY
  if (clip.blurAmount !== undefined) fields.blurAmount = clip.blurAmount
  if (clip.backgroundDim !== undefined) fields.backgroundDim = clip.backgroundDim
  return fields
}

export function editorFrameFields(clip: {
  fit: string
  focusX?: number
  focusY?: number
  blurAmount?: number
  backgroundDim?: number
}): FrameKnobs {
  const fit: ClipFit = clip.fit === 'fill' || clip.fit === 'blur' ? clip.fit : 'fit'
  return montageFrameFields({
    fit,
    focusX: typeof clip.focusX === 'number' ? clip.focusX : undefined,
    focusY: typeof clip.focusY === 'number' ? clip.focusY : undefined,
    blurAmount: typeof clip.blurAmount === 'number' ? clip.blurAmount : undefined,
    backgroundDim: typeof clip.backgroundDim === 'number' ? clip.backgroundDim : undefined,
  })
}

export function clipPreviewClass(fit: ClipFit): string {
  const base = 'absolute inset-0 h-full w-full bg-transparent'
  return fit === 'fill' ? `${base} object-cover` : `${base} object-contain`
}

export function clipObjectPosition(clip: { fit: ClipFit; focusX?: number; focusY?: number }): string | undefined {
  if (clip.fit !== 'fill') return undefined
  return `${clip.focusX ?? 50}% ${clip.focusY ?? 50}%`
}

export function focusPercent(client: number, origin: number, size: number): number {
  if (!(size > 0)) return 50
  return Math.round(Math.min(100, Math.max(0, ((client - origin) / size) * 100)))
}
