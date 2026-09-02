import type { StoryMusicCandidate, StoryMusicCue, StoryProject } from './types'

export type StoryMusicCandidateOption = {
  candidate: StoryMusicCandidate
  cue?: StoryMusicCue
  label: string
}

export function storyProjectPremise(project: StoryProject): string {
  const sourceBrief = project.creativeBrief.generalIdea.trim()
  if (project.projectType === 'music_video') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.performer && `Artista o creador: ${project.creativeBrief.performer}`,
      project.creativeBrief.musicStyle && `Estilo musical: ${project.creativeBrief.musicStyle}`,
      project.creativeBrief.songStory && `La canción cuenta: ${project.creativeBrief.songStory}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'quick_video') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonistas: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `Lugar: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Acción o diálogo: ${project.creativeBrief.action}`,
      `Formato: ${project.creativeBrief.quickFormat}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'trailer') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonistas: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `Mundo y localizaciones: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Conflicto y promesa del tráiler: ${project.creativeBrief.action}`,
      `Duración objetivo del tráiler: ${project.creativeBrief.durationSeconds}s`,
    ].filter(Boolean).join('\n')
  }
  return [sourceBrief, project.premise].filter(Boolean).join('\n')
}

export function storySongBrief(
  project: StoryProject,
  durationSeconds: number,
  lyricsLanguage = project.language,
): string {
  const cast = project.characters.slice(0, 5).map(character =>
    `${character.name}: ${character.desire}; arc: ${character.arc}`).join(' | ')
  const beats = project.beats.map(beat => `${beat.title}: ${beat.summary}`).join(' → ')
  return [
    `Create an original theme song that tells the story “${project.title}”.`,
    `Write all lyrics in ${lyricsLanguage}. Target approximately ${durationSeconds} seconds.`,
    `Genre and emotional direction: ${project.genre}; ${project.tone}. Theme: ${project.theme}.`,
    `Premise: ${storyProjectPremise(project)}. Synopsis: ${project.synopsis}. Ending: ${project.ending}.`,
    cast ? `Character journeys: ${cast}.` : '',
    beats ? `Narrative progression: ${beats}.` : '',
    project.world.visualLanguage ? `Choose music that feels native to this visual world: ${project.world.visualLanguage}.` : '',
    'Use a memorable recurring chorus, concrete story imagery, and a clear emotional progression; do not merely summarize the synopsis.',
  ].filter(Boolean).join('\n')
}

export const MINIMAX_LYRIC_SECTION = /^\[(Intro|Verse|Pre Chorus|Chorus|Post Chorus|Interlude|Bridge|Transition|Build Up|Break|Hook|Inst|Solo|Outro)\]\s*$/m

export function miniMaxCuePayload(cue: StoryMusicCue, model: StoryProject['music']['model']): string {
  return JSON.stringify({
    model,
    prompt: cue.style.trim().slice(0, 300),
    lyrics: cue.instrumental ? '' : cue.lyrics,
    instrumental: cue.instrumental,
    count: 1,
  }, null, 2)
}

export function musicCandidateDisplayName(
  candidate: StoryMusicCandidate,
  title: string,
  fallbackLanguage: string,
  fallbackVersion: number,
): string {
  if (candidate.displayName?.trim()) return candidate.displayName
  const language = candidate.language?.trim() || fallbackLanguage.trim() || 'Original'
  const version = candidate.version || fallbackVersion
  return `${candidate.title?.trim() || title.trim() || 'Story song'} · ${language} · v${version}`
}

export function nextMusicCandidateVersion(
  candidates: StoryMusicCandidate[],
  language: string,
  fallbackLanguage: string,
): number {
  const normalizedLanguage = (language || fallbackLanguage).trim().toLocaleLowerCase()
  return candidates.reduce((highest, candidate, index) => {
    const candidateLanguage = (candidate.language || fallbackLanguage).trim().toLocaleLowerCase()
    if (candidateLanguage !== normalizedLanguage) return highest
    return Math.max(highest, candidate.version || index + 1)
  }, 0) + 1
}
