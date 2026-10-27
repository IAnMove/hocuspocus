// Montage edits made from the comic view. They change the same clip list and
// the same per-clip extras the timeline saves.

import type { MontageTake, ShotProvenance } from '../../api/montages'

export type ComicTextStyle = 'caption' | 'bubble' | 'none'

export interface ComicChoice {
  frame?: number
  text?: ComicTextStyle
}

export interface ClipExtra {
  takes?: MontageTake[]
  lyric?: string
  comic?: ComicChoice
}

const LYRIC_LIMIT = 500

export function moveClip<T extends { id: string }>(clips: T[], movingId: string, insertionIndex: number): T[] {
  const sourceIndex = clips.findIndex(clip => clip.id === movingId)
  if (sourceIndex < 0) return clips
  const moving = clips[sourceIndex]
  const without = clips.filter(clip => clip.id !== movingId)
  const adjusted = insertionIndex > sourceIndex ? insertionIndex - 1 : insertionIndex
  without.splice(Math.max(0, Math.min(without.length, adjusted)), 0, moving)
  return without
}

export interface ComicExtraPatch {
  lyric?: string | null
  comic?: { frame?: number | null; text?: ComicTextStyle | null }
}

export function patchClipExtra(current: ClipExtra | undefined, patch: ComicExtraPatch): ClipExtra | undefined {
  const next: ClipExtra = { ...(current ?? {}) }
  if (patch.lyric !== undefined) applyLyric(next, patch.lyric)
  if (patch.comic) applyComic(next, patch.comic)
  if (!next.lyric && !next.takes?.length && !next.comic) return undefined
  return next
}

function applyLyric(next: ClipExtra, lyric: string | null): void {
  const text = (lyric ?? '').trim().slice(0, LYRIC_LIMIT)
  if (text) next.lyric = text
  else delete next.lyric
}

function applyComic(next: ClipExtra, patch: { frame?: number | null; text?: ComicTextStyle | null }): void {
  const comic: ComicChoice = { ...(next.comic ?? {}) }
  if (patch.text !== undefined) {
    if (patch.text) comic.text = patch.text
    else delete comic.text
  }
  if (patch.frame !== undefined) {
    if (patch.frame === null || Number.isNaN(patch.frame)) delete comic.frame
    else comic.frame = Math.min(36000, Math.max(0, patch.frame))
  }
  if (comic.frame === undefined && !comic.text) delete next.comic
  else next.comic = comic
}

/** A comic duplicate keeps the line and the panel choice. Takes stay on the original. */
export function duplicateClipState<T extends { id: string; name: string }>(
  clip: T, extra: ClipExtra | undefined, newId: string,
): { clip: T; extra?: ClipExtra } {
  const copied: ClipExtra = {}
  if (extra?.lyric) copied.lyric = extra.lyric
  if (extra?.comic) copied.comic = { ...extra.comic }
  const name = clip.name.endsWith(' (copy)') ? clip.name : `${clip.name} (copy)`
  return { clip: { ...clip, id: newId, name }, extra: copied.lyric || copied.comic ? copied : undefined }
}

/** Seconds inside the trimmed clip. `at` from the server is an absolute source time. */
export function frameOffset(trimStart: number, at: number): number {
  return Math.max(0, Math.round((at - trimStart) * 1000) / 1000)
}

/** The outputs whose sidecar can hold a clip's generation settings: the one the montage names (a copied
 * clip keeps its settings under the original's name), then the generated file itself. */
export function creationOutputs(origin: ShotProvenance): string[] {
  const named = origin.sidecar ? [origin.sidecar.replace(/\.meta\.json$/, '.mp4')] : []
  return [...new Set([...named, ...(origin.generatedFrom ? [origin.generatedFrom] : [])])]
}

/** After Regenerar / Usar take writes the saved montage, keep the editor's unsaved clips,
 * trims, lyrics and panel choices. A take select also overlays that clip's new media. */
export function mergeComicShotUpdate<T extends { id: string }>(
  clips: T[],
  extras: Record<string, ClipExtra | undefined>,
  savedClips: Array<{ id: string; takes?: MontageTake[] }>,
  adopted: (Partial<T> & { id: string }) | undefined,
): { clips: T[]; extras: Record<string, ClipExtra> } {
  const nextClips = adopted
    ? clips.map(clip => clip.id === adopted.id ? { ...clip, ...adopted } : clip)
    : clips
  const nextExtras: Record<string, ClipExtra> = {}
  for (const [id, extra] of Object.entries(extras)) {
    if (extra) nextExtras[id] = extra
  }
  for (const clip of savedClips) {
    if (!clip.takes?.length) continue
    nextExtras[clip.id] = { ...nextExtras[clip.id], takes: clip.takes }
  }
  return { clips: nextClips, extras: nextExtras }
}
