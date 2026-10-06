// Conversions between the Video Editor draft and a server-side montage document.
// A montage keeps captions (image overlays) and narration (audio cues) as timed,
// editable layers instead of burning them into clips.
import type { MontageAudioCue, MontageClip, MontageDocument, MontageOverlay } from '../../api/montages'
import type { VideoEditorProbe } from '../../api/client'
import type { ResolutionOption, EditorSoundtrack } from './editorDraft'
import { RESOLUTIONS } from './editorDraft'
import type { EditorClip, Transition } from './editorClipNormalization'
import { editorFrameFields, montageFrameFields } from './clipFrame'

export interface MontageLayers {
  overlays: MontageOverlay[]
  audioCues: MontageAudioCue[]
  duck: number
}

export interface MontageRef {
  file: string
  revision: number
  origins: Record<string, MontageClip['origin']>
  /** Takes and lyric per clip id, kept untouched by editor saves. */
  extras?: Record<string, Pick<MontageClip, 'takes' | 'lyric'>>
  notes?: string
}

export const EMPTY_LAYERS: MontageLayers = { overlays: [], audioCues: [], duck: 0 }
const LAYERS_KEY = 'maestro-video-editor-montage-v1'
const TRANSITIONS = new Set<Transition>(['none', 'crossfade', 'fade-black', 'wipe-left', 'slide-left', 'slide-right', 'circle-open', 'dissolve', 'pixelize', 'blur', 'zoom-in', 'later-clock', 'later-tropical', 'later-cinematic'])

export function montageFromEditor(input: {
  projectName: string
  resolution: ResolutionOption
  fps: number
  clips: EditorClip[]
  soundtrack: EditorSoundtrack | null
  layers: MontageLayers
  origins?: MontageRef['origins']
  extras?: MontageRef['extras']
  notes?: string
}): MontageDocument {
  return {
    version: 1,
    kind: 'montage',
    name: input.projectName.trim() || 'montage',
    width: input.resolution.width,
    height: input.resolution.height,
    fps: input.fps,
    clips: input.clips.map(clip => ({
      id: clip.id,
      name: clip.name,
      source: clip.source,
      trimStart: clip.trimStart,
      trimEnd: clip.trimEnd,
      volume: clip.volume,
      muted: clip.muted,
      ...montageFrameFields(clip),
      transition: clip.transition,
      transitionDuration: clip.transitionDuration,
      transitionText: clip.transitionText,
      transitionTextSize: clip.transitionTextSize,
      ...(input.origins?.[clip.id] ? { origin: input.origins[clip.id] } : {}),
      ...(input.extras?.[clip.id] ?? {}),
    })),
    soundtrack: input.soundtrack ? {
      name: input.soundtrack.name,
      source: input.soundtrack.source,
      trimStart: input.soundtrack.trimStart,
      trimEnd: input.soundtrack.trimEnd,
      volume: input.soundtrack.volume,
      loop: input.soundtrack.loop,
    } : null,
    overlays: input.layers.overlays,
    audioCues: input.layers.audioCues,
    duck: input.layers.duck,
    ...(input.notes ? { notes: input.notes } : {}),
  }
}

export function resolutionFor(width: number, height: number): ResolutionOption {
  return RESOLUTIONS.find(option => option.width === width && option.height === height)
    ?? { label: `${width}×${height}`, width, height }
}

/** Build editor clips from a montage; `probe` reads real media facts per source. */
export async function editorFromMontage(
  montage: MontageDocument,
  probe: (source: string) => Promise<VideoEditorProbe>,
  probeAudio: (source: string) => Promise<{ duration: number }>,
  thumbnail: (source: string) => string,
): Promise<{ clips: EditorClip[]; soundtrack: EditorSoundtrack | null; layers: MontageLayers; origins: MontageRef['origins']; extras: NonNullable<MontageRef['extras']> }> {
  const clips: EditorClip[] = []
  const origins: MontageRef['origins'] = {}
  const extras: NonNullable<MontageRef['extras']> = {}
  for (const clip of montage.clips) {
    const facts = await probe(clip.source)
    const trimEnd = clip.trimEnd > clip.trimStart ? Math.min(clip.trimEnd, facts.duration || clip.trimEnd) : facts.duration
    clips.push({
      ...facts,
      id: clip.id,
      name: clip.name,
      source: clip.source,
      previewUrl: clip.source,
      thumbnailUrl: thumbnail(clip.source),
      trimStart: clip.trimStart,
      trimEnd,
      volume: clip.volume,
      muted: clip.muted,
      ...editorFrameFields(clip),
      transition: TRANSITIONS.has(clip.transition as Transition) ? clip.transition as Transition : 'none',
      transitionDuration: clip.transitionDuration,
      transitionText: clip.transitionText,
      transitionTextSize: clip.transitionTextSize,
    })
    if (clip.origin) origins[clip.id] = clip.origin
    if (clip.takes?.length || clip.lyric) extras[clip.id] = { ...(clip.takes?.length ? { takes: clip.takes } : {}), ...(clip.lyric ? { lyric: clip.lyric } : {}) }
  }
  let soundtrack: EditorSoundtrack | null = null
  if (montage.soundtrack) {
    const facts = await probeAudio(montage.soundtrack.source)
    soundtrack = {
      name: montage.soundtrack.name,
      source: montage.soundtrack.source,
      duration: facts.duration,
      trimStart: montage.soundtrack.trimStart,
      trimEnd: montage.soundtrack.trimEnd || facts.duration,
      volume: montage.soundtrack.volume,
      loop: montage.soundtrack.loop,
    }
  }
  return { clips, soundtrack, layers: { overlays: montage.overlays ?? [], audioCues: montage.audioCues ?? [], duck: montage.duck ?? 0 }, origins, extras }
}

/** Snake-case layer fields for POST /api/v1/video-editor/export. */
export function exportLayerFields(layers: MontageLayers) {
  if (!layers.overlays.length && !layers.audioCues.length) return {}
  return {
    overlays: layers.overlays.map(item => ({ id: item.id, name: item.name, source: item.source, start: item.start, end: item.end, x: item.x, y: item.y, width: item.width, opacity: item.opacity, fade_in: item.fadeIn, fade_out: item.fadeOut })),
    audio_cues: layers.audioCues.map(item => ({ id: item.id, name: item.name, source: item.source, start: item.start, volume: item.volume, trim_start: item.trimStart, trim_end: item.trimEnd })),
    duck: layers.duck,
  }
}

export function loadMontageState(workspace: string): { layers: MontageLayers; ref: MontageRef | null } {
  try {
    const raw = window.localStorage.getItem(`${LAYERS_KEY}:${encodeURIComponent(workspace)}`)
    if (!raw) return { layers: EMPTY_LAYERS, ref: null }
    const parsed = JSON.parse(raw) as { layers?: MontageLayers; ref?: MontageRef | null }
    return { layers: { ...EMPTY_LAYERS, ...parsed.layers }, ref: parsed.ref ?? null }
  } catch {
    return { layers: EMPTY_LAYERS, ref: null }
  }
}

/** Another part of the app (the Wizard's export) saved the open draft as a montage: the editor takes its new ref. */
export const MONTAGE_REF_EVENT = 'hocuspocus:video-editor-montage-ref'

export function announceMontageRef(workspace: string, layers: MontageLayers, ref: MontageRef): void {
  persistMontageState(workspace, layers, ref)
  if (typeof window !== 'undefined') window.dispatchEvent(new window.CustomEvent(MONTAGE_REF_EVENT, { detail: { workspace, ref } }))
}

export function persistMontageState(workspace: string, layers: MontageLayers, ref: MontageRef | null): void {
  try {
    window.localStorage.setItem(`${LAYERS_KEY}:${encodeURIComponent(workspace)}`, JSON.stringify({ layers, ref }))
  } catch {
    // Browser storage is a convenience; the server montage is the durable copy.
  }
}
