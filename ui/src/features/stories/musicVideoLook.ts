import type { StoryProject } from './types'
import { normalizeLanguageIntent } from '../../lib/languageIntent'

// Re-export the song-specific language contract through this already shared
// music-video boundary. Agent reconciliation can resolve lyric language
// without growing its legacy module graph with another direct dependency.
export { extractRequestedSongLanguage, resolveSongLyricsLanguage } from './songLanguage'

const NAMED_LOOK = /\b(pel[ií]cula|film\b|movie\b|serie\b|series\b|anthology|animaci[oó]n de |animated (?:film|series)|studio ghibli|ghibli)\b/i
const YEAR_LOOK = /\b((?:19|20)\d{2})\b.{0,48}\b(film|movie|pel[ií]cula|animated|animaci[oó]n|anthology)\b/i
const YEAR_LOOK_FLIP = /\b(film|movie|pel[ií]cula|animated|animaci[oó]n|anthology)\b.{0,48}\b((?:19|20)\d{2})\b/i
const HEAVY_METAL_1981 = /\bheavy metal\b.{0,24}\b1981\b|\b1981\b.{0,24}\bheavy metal\b/i
const GENERIC_VISUAL_STYLE = /^(?:direcci[oó]n visual cinematogr[aá]fica coherente, personajes legibles y continuidad entre escenas\.?|identidades consistentes, siluetas reconocibles y expresiones claras\.?)$/i
const NEW_SONG_REQUESTS = [
  /\b(?:videoclip|clip\s+musical)\b[^.!?\n]{0,160}\b(?:de|con|para)\s+una\s+canci[oó]n\b/i,
  /\bmusic\s*video\b[^.!?\n]{0,160}\b(?:for|with|of)\s+(?:an?\s+)?(?:new\s+|original\s+)?song\b/i,
  /\b(?:clip\s+musical|vid[eé]oclip)\b[^.!?\n]{0,160}\b(?:d['’]une|avec\s+une)\s+chanson\b/i,
  /\b(?:videoclip|clip\s+musicale)\b[^.!?\n]{0,160}\b(?:di|con)\s+una\s+canzone\b/i,
  /\bvideoclipe\b[^.!?\n]{0,160}\b(?:de|com)\s+uma\s+can[cç][aã]o\b/i,
]
const EXISTING_SONG_REQUESTS = [
  /\b(?:esta|esa|la)\s+canci[oó]n\s+(?:seleccionada|actual|abierta|existente)\b/i,
  // Reuse needs an explicit possession/selection signal. A relative clause
  // such as "una canción que está inspirada en…" still describes a new song.
  /\bcanci[oó]n\s+(?:que\s+)?ya\s+(?:est[aá]|tengo|tenemos|creamos|generamos)\b/i,
  /\bcanci[oó]n\s+que\s+est[aá]\s+(?:seleccionada|actual|abierta|existente|creada|generada|lista)\b/i,
  // "tenemos que crear" is an obligation, not possession of an existing cue.
  /\bcanci[oó]n\s+(?:que\s+)?(?:tengo|tenemos|creamos|generamos)\b(?!\s+que\b)/i,
  /\b(?:selected|current|open|existing|this|that)\s+song\b/i,
  /\b(?:use|usa|utiliza|emplea)\b[^.!?\n]{0,80}\b(?:esa|esta|la|that|this)\s+(?:versi[oó]n|version|canci[oó]n|song)\b/i,
]
const LANGUAGE_ALIASES: Array<[RegExp, string]> = [
  [/^(?:espa|castellano|spanish)/, 'es'],
  [/^(?:english|ingl)/, 'en'],
  [/^(?:fran|french)/, 'fr'],
  [/^(?:deutsch|alem|german)/, 'de'],
  [/^(?:ital)/, 'it'],
  [/^(?:port)/, 'pt'],
]

export interface NewMusicVideoIntent {
  title: string
  topic: string
  protagonist: string
  language: string
  durationSeconds: number
}

export function isNewMusicVideoSongRequest(request: string): boolean {
  const text = request.trim()
  if (!text || EXISTING_SONG_REQUESTS.some(pattern => pattern.test(text))) return false
  return NEW_SONG_REQUESTS.some(pattern => pattern.test(text))
}

function musicVideoLanguage(request: string, conversationLanguage: string): string {
  const explicit = request.match(
    /\b(?:en|in|language|idioma|langue|sprache|lingua)\s+(espa[nñ]ol|castellano|spanish|english|ingl[eé]s|fran[cç]ais|franc[eé]s|french|deutsch|alem[aá]n|german|italiano|italian|portugu[eê]s|portuguese)\b/i,
  )?.[1]?.toLocaleLowerCase()
  const explicitCode = explicit
    ? LANGUAGE_ALIASES.find(([pattern]) => pattern.test(explicit))?.[1] || ''
    : ''
  if (explicitCode || conversationLanguage) return explicitCode || conversationLanguage
  if (/\b(?:hazme|canci[oó]n|pel[ií]cula|dibujos?|protagonista|luche|contra)\b/i.test(request)) return 'es'
  if (/\b(?:make|song|movie|animated|protagonist|fight|against)\b/i.test(request)) return 'en'
  return ''
}

export function parseNewMusicVideoIntent(request: string, conversationLanguage = ''): NewMusicVideoIntent {
  const exactTitle = request.match(
    /\b(?:videoclip|music\s*video|clip\s+musical)\b[^.!?\n]{0,100}\b(?:titulado|llamado|titled|named)\s+(?:exactamente\s+)?["“]([^"”]+)["”]/i,
  )?.[1]?.trim().slice(0, 300) || ''
  const extractedTopic = request.match(
    /\b(?:en\s+la\s+que|en\s+el\s+que|donde|sobre|acerca\s+de|where|about|featuring)\s+(.+?)(?=\s+(?:en|con|in|with)\s+(?:(?:un|una|an?|the)\s+)?(?:estilo|style|look|est[eé]tica|visual)|[.!?\n]|$)/i,
  )?.[1]?.trim()
  const topic = (extractedTopic || request).replace(/\s+/g, ' ').slice(0, 300)
  const protagonist = topic.match(
    /^(.{2,100}?)\s+(?:sea|es|be|is)\s+(?:(?:el|la|un|una|the|a)\s+)?protagonist[ae]?\b/i,
  )?.[1]?.trim() || ''
  const requestedDuration = Number(request.match(/\b(\d{1,4})\s*(?:segundos?|seconds?|secondes?|secondi)\b/i)?.[1] || 90)
  return {
    title: (exactTitle || protagonist || topic || 'Nuevo videoclip').slice(0, 300),
    topic,
    protagonist,
    language: musicVideoLanguage(request, conversationLanguage),
    durationSeconds: Math.min(3_600, Math.max(15, requestedDuration)),
  }
}

export function newMusicVideoStoryAction(request: string, conversationLanguage = '') {
  const { title, topic, protagonist, language, durationSeconds } = parseNewMusicVideoIntent(request, conversationLanguage)
  const languageIntent = language ? normalizeLanguageIntent({
    conversation_language: conversationLanguage || language,
    content_language: language,
    spoken_language: language,
    technical_prompt_language: 'en',
  }) : undefined
  return {
    type: 'create_story' as const,
    title,
    projectType: 'music_video' as const,
    creativeBrief: request.trim().slice(0, 4_000),
    premise: topic,
    logline: topic,
    synopsis: request.trim().slice(0, 6_000),
    theme: topic,
    ending: `El conflicto central de ${topic} alcanza una resolución visual y musical clara.`,
    genre: 'Videoclip musical',
    tone: 'Cinematográfico',
    visualStyle: request.trim().slice(0, 2_000),
    worldSummary: topic,
    language,
    characters: protagonist ? [{
      name: protagonist,
      role: 'Protagonista',
      personality: '',
      desire: 'Superar el conflicto central de la canción.',
      flaw: '',
      appearance: '',
      voice: '',
    }] : [],
    locations: [],
    outlineBeats: [topic],
    durationSeconds,
    ...(languageIntent ? { languageIntent } : {}),
  }
}

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
