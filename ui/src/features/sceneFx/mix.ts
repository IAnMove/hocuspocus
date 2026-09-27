import { scheduleFx } from './audio'
import type { SceneFx } from './types'

export async function mixFxAudio(cues: SceneFx[] | undefined, duration: number) {
  if (!cues?.some(cue => cue.sound && cue.volume)) return undefined
  if (!Number.isFinite(duration) || duration <= 0 || duration > 180) throw new Error('SFX audio exports support up to 180 seconds per scene.')
  const context = new OfflineAudioContext(2, Math.ceil(duration * 48000), 48000)
  scheduleFx(context, cues, duration)
  return context.startRendering()
}
