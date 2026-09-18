import { filenameOf, text, uniqueStrings } from './fields.ts'
import type { ClipRefsLike, PipelineClipLike, TakeRecord } from './types.ts'

function listFrom(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return uniqueStrings(value.map(item => filenameOf(item)))
}

export function refsFromManifest(refs: ClipRefsLike | null | undefined): string[] {
  if (!refs) return []
  return uniqueStrings([
    ...listFrom(refs.image_references),
    ...listFrom(refs.video_references),
    ...listFrom(refs.audio_references),
    filenameOf(refs.shot_frame),
  ])
}

export function clipRefs(clip: PipelineClipLike): string[] {
  return uniqueStrings([
    ...refsFromManifest(clip.h3_references),
    filenameOf(clip.start_image_filename),
    ...listFrom(clip.keyframe_filenames),
  ])
}

export function recordRefs(record: TakeRecord | undefined): string[] {
  const parents = record?.lineage?.parents || []
  return uniqueStrings(parents.map(item => filenameOf(item.uri) || text(item.kind)))
}
