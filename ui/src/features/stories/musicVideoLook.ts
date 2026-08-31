import type { StoryProject } from './types'

const NAMED_LOOK = /\b(pel[ií]cula|film\b|movie\b|serie\b|series\b|anthology|animaci[oó]n de |animated (?:film|series)|studio ghibli|ghibli)\b/i
const YEAR_LOOK = /\b((?:19|20)\d{2})\b.{0,48}\b(film|movie|pel[ií]cula|animated|animaci[oó]n|anthology)\b/i
const YEAR_LOOK_FLIP = /\b(film|movie|pel[ií]cula|animated|animaci[oó]n|anthology)\b.{0,48}\b((?:19|20)\d{2})\b/i
const HEAVY_METAL_1981 = /\bheavy metal\b.{0,24}\b1981\b|\b1981\b.{0,24}\bheavy metal\b/i
const GENERIC_VISUAL_STYLE = /^(?:direcci[oó]n visual cinematogr[aá]fica coherente, personajes legibles y continuidad entre escenas\.?|identidades consistentes, siluetas reconocibles y expresiones claras\.?)$/i

export function namedFilmOrSeriesLook(style: string): boolean {
  const text = String(style || '').trim()
  if (!text) return false
  return NAMED_LOOK.test(text) || YEAR_LOOK.test(text) || YEAR_LOOK_FLIP.test(text) || HEAVY_METAL_1981.test(text)
}

export function resolveMusicVideoVisualStyle(
  projectType: StoryProject['projectType'],
  visualStyle: string,
  creativeBrief: string,
): string {
  const style = String(visualStyle || '').trim()
  const brief = String(creativeBrief || '').trim()
  if (projectType !== 'music_video') return style
  if (style && !GENERIC_VISUAL_STYLE.test(style)) return style
  if (brief && namedFilmOrSeriesLook(brief)) return brief
  return style
}

export function musicVideoShouldUseDirectVideo(project: Pick<StoryProject, 'musicVideoGenerationMode' | 'visualStyle' | 'characterVisualStyle'>): boolean {
  if (project.musicVideoGenerationMode === 'direct_video') return true
  if (project.musicVideoGenerationMode === 'direct_references') return false
  return namedFilmOrSeriesLook(`${project.visualStyle}\n${project.characterVisualStyle}`)
}

export function applyMusicVideoDirectVideoDefaults(project: StoryProject): StoryProject {
  if (project.projectType !== 'music_video') return project
  if (project.musicVideoGenerationMode === 'direct_references') return project
  if (!musicVideoShouldUseDirectVideo(project)) return project
  return withDirectVideoLock(project)
}

function withDirectVideoLock(project: StoryProject): StoryProject {
  const style = [project.visualStyle, project.characterVisualStyle].filter(Boolean).join('\n')
  const lock = [
    style,
    'Native MiniMax H3 text-to-video. Do not generate a start-frame still and do not use live-action or photoreal stills of the named film or series as image references; match that look from this text lock.',
  ].filter(Boolean).join('\n\n')
  return {
    ...project,
    musicVideoGenerationMode: 'direct_video',
    protagonistConsistency: false,
    directVideoMasterPromptMode: style.trim() ? 'custom' : project.directVideoMasterPromptMode,
    directVideoMasterPrompt: project.directVideoMasterPromptMode === 'custom' && project.directVideoMasterPrompt.trim()
      ? project.directVideoMasterPrompt
      : lock || project.directVideoMasterPrompt,
    videoOverride: {
      ...project.videoOverride,
      model: project.videoOverride.model || 'minimax_h3_legacy',
    },
  }
}

export function inferStoryProjectTypeFromText(...parts: string[]): 'music_video' | 'trailer' | 'quick_video' | null {
  const blob = parts.filter(Boolean).join('\n')
  if (!blob.trim()) return null
  if (/\b(videoclip|videoclips|music\s*videos?|clip\s+musical|v[ií]deo\s+musical)\b/i.test(blob)) return 'music_video'
  if (/\b(tr[aá]iler|trailers?)\b/i.test(blob)) return 'trailer'
  if (/\b(v[ií]deo\s+r[aá]pido|quick\s*videos?)\b/i.test(blob)) return 'quick_video'
  return null
}
