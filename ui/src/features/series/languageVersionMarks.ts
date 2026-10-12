import type { SeriesEpisode, SeriesLanguageVersion } from './types'

/** What a language version still has as machine translation (`machineTranslated`, from `series.episode.translate`). */
export interface MachineMarks {
  lines: Set<string>
  cards: Set<string>
  title: boolean
  /** Who asked for the translation (user, agent, wizard, server); '' when unknown. */
  requestedBy: string
  /** Lines, cards and the title still marked. */
  count: number
}

export type VersionCardText = { title: string; body: string }

/** A card of the original episode: the shot it belongs to and its text in the series' own language. */
export interface EpisodeCard extends VersionCardText { shotId: string }

export function machineMarks(version: SeriesLanguageVersion | undefined): MachineMarks {
  const marks = version?.machineTranslated
  const lines = new Set((marks?.dialogue ?? []).filter(id => typeof version?.dialogue[id] === 'string'))
  const cards = new Set((marks?.cards ?? []).filter(id => Boolean(version?.cards[id])))
  const title = marks?.title === true && Boolean(version?.title?.trim())
  return { lines, cards, title, requestedBy: marks?.requestedBy ?? '', count: lines.size + cards.size + (title ? 1 : 0) }
}

/** The write a person makes to mark every machine-translated text as checked: each text as it is now. */
export function checkedWrite(version: SeriesLanguageVersion, marks: MachineMarks): { dialogue: Record<string, string>; cards: Record<string, VersionCardText>; title?: string } {
  return {
    dialogue: Object.fromEntries([...marks.lines].map(id => [id, version.dialogue[id]])),
    cards: Object.fromEntries([...marks.cards].map(id => [id, version.cards[id]])),
    ...(marks.title ? { title: version.title ?? '' } : {}),
  }
}

/** The title and end cards of the original, in shot order. */
export function episodeCards(episode: SeriesEpisode): EpisodeCard[] {
  return episode.shots.flatMap(shot => {
    const card = shot.layout2d?.card
    if (!card || typeof card !== 'object') return []
    const { title, body } = card as { title?: unknown; body?: unknown }
    return [{ shotId: shot.id, title: typeof title === 'string' ? title : '', body: typeof body === 'string' ? body : '' }]
  })
}
