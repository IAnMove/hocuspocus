import type { StoryMusicCandidate, StoryMusicCue, StoryProject } from './types'

export const SYNTHETIC_STORY_SONG_CUE_ID = 'story-song'

const normalizeName = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

export interface StoryMusicSelection {
  cue?: StoryMusicCue
  candidate: StoryMusicCandidate
}

export function isReadyStoryMusicCandidate(candidate: StoryMusicCandidate): boolean {
  if (candidate.status === 'pending' || candidate.status === 'failed') return false
  return Boolean((candidate.source || '').trim())
}

function candidateNames(candidate: StoryMusicCandidate): string[] {
  return [candidate.displayName, candidate.title, candidate.name]
    .map(value => normalizeName(value || ''))
    .filter(Boolean)
}

function candidateAliases(candidate: StoryMusicCandidate): string[] {
  const names = candidateNames(candidate)
  const display = normalizeName(candidate.displayName || '')
  // A resumed Wizard turn can retain the pre-render label ("Cue · Español")
  // while the persisted candidate is versioned ("Cue · Español · v2"). This
  // is the only compatibility alias allowed; arbitrary names must not fall
  // back to a sole candidate from an unrelated request.
  const versionless = display.replace(/\s+v\d+$/i, '').trim()
  return Array.from(new Set(versionless ? [...names, versionless] : names))
}

function allCandidates(project: StoryProject, cue?: StoryMusicCue): StoryMusicCandidate[] {
  const seen = new Set<string>()
  const list: StoryMusicCandidate[] = []
  const push = (candidate: StoryMusicCandidate) => {
    if (seen.has(candidate.id)) return
    seen.add(candidate.id)
    list.push(candidate)
  }
  ;(cue?.candidates || []).forEach(push)
  project.music.cues.forEach(item => item.candidates.forEach(push))
  project.music.candidates.forEach(push)
  return list
}

function resolveCueIdentity(
  project: StoryProject,
  cueTitle: string,
  cueId: string,
  candidateId = '',
): { cue?: StoryMusicCue; scopedCue?: StoryMusicCue; candidateFromTitle?: StoryMusicCandidate } {
  const requested = normalizeName(cueTitle)
  const requestedCandidateId = candidateId.trim()
  const cueById = cueId ? project.music.cues.find(item => item.id === cueId) : undefined
  if (cueId && !cueById) throw new Error(`No existe el cue con ID “${cueId}” en “${project.title}”.`)
  const candidates = cueById ? cueById.candidates : allCandidates(project)
  const titleMatches = requested
    ? candidates.filter(item => candidateAliases(item).includes(requested))
    : []
  if (titleMatches.length > 1 && !requestedCandidateId) {
    throw new Error(`Hay varias versiones de canción llamadas “${cueTitle}”; usa su candidate_id exacto.`)
  }
  const candidateFromTitle = titleMatches.length === 1 ? titleMatches[0] : undefined
  const candidateCue = candidateFromTitle
    ? project.music.cues.find(item => item.candidates.some(candidate => candidate.id === candidateFromTitle.id))
    : undefined
  const exactCues = requested
    ? project.music.cues.filter(item => normalizeName(item.title) === requested)
    : []
  if (exactCues.length > 1) throw new Error(`Hay varios cues llamados “${cueTitle}”; usa el título exacto y único.`)
  if (requested && !cueById && !candidateFromTitle && !exactCues.length) {
    throw new Error(`No existe el cue “${cueTitle}” en “${project.title}”.`)
  }
  const selectedCue = project.music.cues.find(item => (
    item.selectedCandidateId
    && item.candidates.some(candidate => candidate.id === item.selectedCandidateId)
  ))
  const cue = cueById || candidateCue || exactCues[0]
    || (project.music.cues.length === 1 ? project.music.cues[0] : selectedCue)
  return { cue, scopedCue: cueById || candidateCue || exactCues[0], candidateFromTitle }
}

function resolveCandidateIdentity(
  project: StoryProject,
  pool: StoryMusicCandidate[],
  cue: StoryMusicCue | undefined,
  candidateFromTitle: StoryMusicCandidate | undefined,
  songName: string,
  candidateId: string,
): StoryMusicCandidate {
  const requestedId = candidateId.trim()
  const byId = requestedId ? pool.find(item => item.id === requestedId) : undefined
  if (requestedId && !byId) {
    throw new Error(`No existe la versión de canción con ID “${requestedId}” en “${project.title}”.`)
  }
  const requestedSong = normalizeName(songName)
  if (requestedSong) {
    const matches = pool.filter(item => candidateAliases(item).includes(requestedSong))
    if (matches.length > 1) throw new Error(`Hay varias canciones llamadas “${songName}”; usa el nombre exacto y único.`)
    if (byId && matches.length && matches[0].id !== byId.id) {
      throw new Error(`La canción “${songName}” no coincide con la versión ${requestedId}.`)
    }
    const candidate = byId || matches[0]
    if (candidate) return candidate
    throw new Error(`No existe la canción “${songName}” en “${project.title}”.`)
  }
  if (byId || candidateFromTitle) return (byId || candidateFromTitle)!
  const selectedId = cue?.selectedCandidateId || project.music.selectedCandidateId
  const selected = selectedId ? pool.find(item => item.id === selectedId) : undefined
  if (selected) return selected
  if (pool.length === 1) return pool[0]
  throw new Error(`Hay ${pool.length} canciones en “${project.title}”. Di el nombre exacto de la canción o del cue.`)
}

export function resolveStoryMusicSelection(
  project: StoryProject,
  songName = '',
  cueTitle = '',
  cueId = '',
  candidateId = '',
): StoryMusicSelection {
  const { cue, scopedCue, candidateFromTitle } = resolveCueIdentity(
    project, cueTitle, cueId, candidateId,
  )
  const pool = scopedCue ? scopedCue.candidates : allCandidates(project, cue)
  if (!pool.length) {
    throw new Error(`“${project.title}” no tiene ninguna canción candidata. Genera o importa una en Story Lab → Music.`)
  }
  const candidate = resolveCandidateIdentity(
    project, pool, cue, candidateFromTitle, songName, candidateId,
  )
  assertReadyStoryMusicCandidate(candidate)
  const owningCue = cue || project.music.cues.find(item => item.candidates.some(itemCandidate => itemCandidate.id === candidate.id))
  assertPersistedMusicCue(project, candidate, owningCue, cueId)
  return { cue: owningCue, candidate }
}

function songLabel(candidate: StoryMusicCandidate): string {
  return candidate.displayName || candidate.title || candidate.name || candidate.id
}

function assertReadyStoryMusicCandidate(candidate: StoryMusicCandidate): void {
  if (isReadyStoryMusicCandidate(candidate)) return
  const label = songLabel(candidate)
  if (candidate.status === 'pending') {
    throw new Error(`La canción “${label}” todavía se está generando; espera a que quede lista antes de preparar el videoclip.`)
  }
  if (candidate.status === 'failed') {
    throw new Error(`La canción “${label}” falló y no se puede usar para un videoclip. Genera otra versión.`)
  }
  throw new Error(`La canción “${label}” no tiene un archivo de audio.`)
}

function assertPersistedMusicCue(
  project: StoryProject,
  candidate: StoryMusicCandidate,
  owningCue: StoryMusicCue | undefined,
  cueId: string,
): void {
  const requestedCueId = cueId.trim()
  if (owningCue && owningCue.id !== SYNTHETIC_STORY_SONG_CUE_ID) return
  if (requestedCueId === SYNTHETIC_STORY_SONG_CUE_ID) return
  throw new Error(`La canción “${songLabel(candidate)}” no pertenece a un cue persistido en “${project.title}”.`)
}

function syntheticStorySongCue(project: StoryProject, candidate: StoryMusicCandidate): StoryMusicCue {
  const lyrics = candidate.lyrics || project.music.lyrics || ''
  return {
    id: SYNTHETIC_STORY_SONG_CUE_ID,
    kind: 'story',
    targetId: project.id,
    title: candidate.title || candidate.displayName || candidate.name,
    purpose: project.music.brief || `Tell ${project.title} as a song-led visual story.`,
    referenceSong: '',
    brief: project.music.brief || '',
    style: candidate.prompt || project.music.style || '',
    lyrics,
    lyriaPrompt: '',
    instrumental: !lyrics.trim(),
    durationSeconds: candidate.durationSeconds || project.music.targetDurationSeconds,
    candidates: [candidate],
    selectedCandidateId: candidate.id,
  }
}

export function effectiveStoryMusicCue(
  project: StoryProject,
  cue: StoryMusicCue | undefined,
  candidate: StoryMusicCandidate,
  requestedCueId = '',
): StoryMusicCue {
  if (cue && cue.id !== SYNTHETIC_STORY_SONG_CUE_ID) return cue
  if (requestedCueId.trim() !== SYNTHETIC_STORY_SONG_CUE_ID) {
    throw new Error(`“${project.title}” no tiene un cue persistido para esta canción.`)
  }
  return cue || syntheticStorySongCue(project, candidate)
}
