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
  // Models occasionally put the selected rendered version ("… · v2") in
  // cue_title. Accept that harmless field mix-up and resolve its owning cue;
  // exact cue titles remain authoritative when they do match.
  const candidateFromCueTitle = requestedCue
    ? allCandidates(project).find(item => candidateNames(item).includes(requestedCue))
    : undefined
  const exactCues = requestedCue
    ? project.music.cues.filter(item => normalizeName(item.title) === requestedCue)
    : []
  if (exactCues.length > 1) {
    throw new Error(`Hay varios cues llamados “${cueTitle}”; usa el título exacto y único.`)
  }
  const cue = requestedCue && !candidateFromCueTitle
    ? exactCues[0] || (project.music.cues.length === 1 ? project.music.cues[0] : undefined)
    : candidateFromCueTitle
      ? project.music.cues.find(item => item.candidates.some(candidate => candidate.id === candidateFromCueTitle.id))
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
  let candidate: StoryMusicCandidate | undefined = candidateFromCueTitle
  if (requestedSong) {
    const matches = pool.filter(item => candidateNames(item).includes(requestedSong))
    if (matches.length > 1) throw new Error(`Hay varias canciones llamadas “${songName}”; usa el nombre exacto y único.`)
    candidate = matches[0] || (pool.length === 1 ? pool[0] : undefined)
    if (!candidate) throw new Error(`No existe la canción “${songName}” en “${project.title}”.`)
  } else if (!candidate) {
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
