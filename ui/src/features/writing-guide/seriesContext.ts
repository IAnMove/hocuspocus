import type { SeriesProject } from '../series/types'
import type { GuideTarget } from './bindings'
import { guideContext, normalizeGuide, type GuideSection, type WritingGuideState } from './model'

/** Episode advice reads the frozen bible, its season's live decisions and that episode's own current decisions. */
export function seriesGuideContext(project: SeriesProject, target: GuideTarget, entity: Record<string, unknown>) {
  const guide = normalizeGuide(project.writingGuide)
  const episode = project.episodesById[target.scope === 'episode' ? target.id : target.episodeId || '']
  if (!episode) {
    const sections = Object.fromEntries(Object.entries(guide.sections).filter(([key]) =>
      !key.startsWith('episode:') && !key.startsWith('scene:') &&
      (!key.startsWith('season:') || target.scope !== 'season' || key === `season:${target.id}`)))
    return guideContext(project as unknown as Record<string, unknown>, entity, { version: 1, sections })
  }
  const snapshot = episode.canonSnapshot
  const frozenNotes = snapshot.writingDecisions as Record<string, Record<string, string>> | undefined
  // Seasons are not canon (their premise and arc are read live by the planner), so their notes stay live too.
  const sections: Record<string, GuideSection> = Object.fromEntries(Object.entries(frozenNotes || {})
    .filter(([key, notes]) => !key.startsWith('season:') && notes && typeof notes === 'object')
    .map(([key, notes]) => [key, { notes }]))
  for (const [key, section] of Object.entries(guide.sections)) {
    if (key === `season:${episode.seasonId}` || key === `episode:${episode.id}` || key.startsWith(`scene:${episode.id}/`)) sections[key] = section
  }
  const decisions: WritingGuideState = { version: 1, sections }
  const context = { ...project, writingEpisode: episode,
    characters: snapshot.characters || project.characters,
    relationships: snapshot.relationships || project.relationships,
    canon: { worldSummary: snapshot.worldSummary ?? project.canon.worldSummary,
      immutableRules: snapshot.immutableRules ?? project.canon.immutableRules },
  }
  return guideContext(context, entity, decisions)
}
