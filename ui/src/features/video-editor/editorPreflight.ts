import { clipTimelineStart, sequenceTotalDuration } from './editorTimeline'
import type { Transition } from './editorClipNormalization'

export type PreflightCode = 'timeline_gap' | 'mixed_fps' | 'mixed_resolution' | 'mix_hot'

export type PreflightNotice = { code: PreflightCode; t: number }

export type PreflightClip = {
  id: string
  fps: number
  width: number
  height: number
  volume: number
  muted: boolean
  hasAudio: boolean
  trimStart: number
  trimEnd: number
  transition: Transition
  transitionDuration: number
}

export type PreflightSoundtrack = { volume: number; trimStart: number; trimEnd: number; loop: boolean }

/** Warnings before an editor export. They never block. */
export function editorPreflight(input: {
  clips: readonly PreflightClip[]
  soundtrack: PreflightSoundtrack | null
}): PreflightNotice[] {
  return [
    ...pictureGaps(input.clips, input.soundtrack),
    ...mixedSources(input.clips),
    ...hotMix(input.clips, input.soundtrack),
  ]
}

function pictureGaps(clips: readonly PreflightClip[], soundtrack: PreflightSoundtrack | null): PreflightNotice[] {
  if (!clips.length) return [{ code: 'timeline_gap', t: 0 }]
  if (!soundtrack || soundtrack.loop) return []
  const picture = sequenceTotalDuration([...clips])
  const audio = Math.max(0, soundtrack.trimEnd - soundtrack.trimStart)
  if (picture - audio <= 0.05) return []
  return [{ code: 'timeline_gap', t: audio }]
}

function mixedSources(clips: readonly PreflightClip[]): PreflightNotice[] {
  const notices: PreflightNotice[] = []
  const fps = clips.filter(clip => clip.fps > 0)
  const otherFps = fps.slice(1).find(clip => Math.abs(clip.fps - fps[0].fps) > 0.5)
  if (otherFps) notices.push({ code: 'mixed_fps', t: at(clips, otherFps) })
  const sized = clips.filter(clip => clip.width > 0 && clip.height > 0)
  const otherSize = sized.slice(1).find(clip => clip.width !== sized[0].width || clip.height !== sized[0].height)
  if (otherSize) notices.push({ code: 'mixed_resolution', t: at(clips, otherSize) })
  return notices
}

function hotMix(clips: readonly PreflightClip[], soundtrack: PreflightSoundtrack | null): PreflightNotice[] {
  if (soundtrack && soundtrack.volume > 1) return [{ code: 'mix_hot', t: 0 }]
  const hot = clips.find(clip => !clip.muted && clip.hasAudio && clip.volume > 1)
  return hot ? [{ code: 'mix_hot', t: at(clips, hot) }] : []
}

function at(clips: readonly PreflightClip[], clip: PreflightClip) {
  const index = clips.indexOf(clip)
  return index < 0 ? 0 : clipTimelineStart([...clips], index)
}
