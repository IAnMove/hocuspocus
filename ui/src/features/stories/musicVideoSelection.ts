import type { StoryMusicCandidate, StoryMusicCue, StoryProject } from './types'

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

function candidateNames(candidate: StoryMusicCandidate): string[] {
  return [candidate.displayName, candidate.title, candidate.name]
    .map(value => normalizeName(value || ''))
    .filter(Boolean)
}

function uniqueMatch<T>(items: T[], predicate: (item: T) => boolean, missing: string, ambiguous: string): T {
  const matches = items.filter(predicate)
  if (!matches.length) throw new Error(missing)
  if (matches.length > 1) throw new Error(ambiguous)
  return matches[0]
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

export function resolveStoryMusicSelection(
  project: StoryProject,
  songName = '',
  cueTitle = '',
): StoryMusicSelection {
  const requestedCue = normalizeName(cueTitle)
  const cue = requestedCue
    ? uniqueMatch(
      project.music.cues,
      item => normalizeName(item.title) === requestedCue,
      `No existe el cue “${cueTitle}” en “${project.title}”.`,
      `Hay varios cues llamados “${cueTitle}”; usa el título exacto y único.`,
    )
    : project.music.cues.length === 1
      ? project.music.cues[0]
      : project.music.cues.find(item => (
        item.selectedCandidateId
        && item.candidates.some(candidate => candidate.id === item.selectedCandidateId)
      ))

  const pool = allCandidates(project, cue)
  if (!pool.length) {
    throw new Error(`“${project.title}” no tiene ninguna canción candidata. Genera o importa una en Story Lab → Music.`)
  }

  const requestedSong = normalizeName(songName)
  let candidate: StoryMusicCandidate | undefined
  if (requestedSong) {
    candidate = uniqueMatch(
      pool,
      item => candidateNames(item).includes(requestedSong),
      `No existe la canción “${songName}” en “${project.title}”.`,
      `Hay varias canciones llamadas “${songName}”; usa el nombre exacto y único.`,
    )
  } else {
    const selectedId = cue?.selectedCandidateId || project.music.selectedCandidateId
    const selected = selectedId ? pool.find(item => item.id === selectedId) : undefined
    if (selected) candidate = selected
    else if (pool.length === 1) candidate = pool[0]
    else {
      throw new Error(`Hay ${pool.length} canciones en “${project.title}”. Di el nombre exacto de la canción o del cue.`)
    }
  }

  if (!candidate.source.trim()) {
    throw new Error(`La canción “${candidate.displayName || candidate.title || candidate.name}” no tiene un archivo de audio.`)
  }

  const owningCue = cue || project.music.cues.find(item => item.candidates.some(itemCandidate => itemCandidate.id === candidate!.id))
  return { cue: owningCue, candidate }
}

export function effectiveStoryMusicCue(
  project: StoryProject,
  cue: StoryMusicCue | undefined,
  candidate: StoryMusicCandidate,
): StoryMusicCue {
  return cue || {
    id: 'story-song',
    kind: 'story',
    targetId: project.id,
    title: candidate.title || candidate.displayName || candidate.name,
    purpose: project.music.brief || `Tell ${project.title} as a song-led visual story.`,
    referenceSong: '',
    brief: project.music.brief,
    style: candidate.prompt || project.music.style,
    lyrics: candidate.lyrics || project.music.lyrics,
    lyriaPrompt: '',
    instrumental: !(candidate.lyrics || project.music.lyrics).trim(),
    durationSeconds: candidate.durationSeconds || project.music.targetDurationSeconds,
    candidates: [candidate],
    selectedCandidateId: candidate.id,
  }
}
