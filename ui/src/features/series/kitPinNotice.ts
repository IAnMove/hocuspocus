import type { CharacterKit } from '../../lib/characterKit'
import type { SeriesEpisode, SeriesProject } from './types'

export interface KitPinNotice {
  kitId: string
  name: string
  pinned: number
  latest: number
}

function pinName(series: SeriesProject, kitId: string, kit: CharacterKit | undefined): string {
  const character = series.characters.find(item => item.voiceProfile?.characterKitRef?.id === kitId)
  return character?.name || kit?.name || kitId
}

/** Pins whose kit has a newer revision. A missing library entry says nothing. */
export function kitPinNotices(series: SeriesProject, episode: SeriesEpisode, kits: CharacterKit[]): KitPinNotice[] {
  const pins = episode.kitPins
  if (!pins) return []
  const byId = new Map(kits.map(kit => [kit.id, kit]))
  const notices: KitPinNotice[] = []
  for (const [kitId, pinned] of Object.entries(pins)) {
    const kit = byId.get(kitId)
    const latest = kit?.revision
    if (latest == null || latest <= pinned) continue
    notices.push({ kitId, name: pinName(series, kitId, kit), pinned, latest })
  }
  return notices
}
