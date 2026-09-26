import { catalogEntry, REMOTE_PROMPT_LIMIT } from '../../lib/musicGenerationSpec'
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
      project.creativeBrief.performer && `Artist or creator: ${project.creativeBrief.performer}`,
      project.creativeBrief.musicStyle && `Music style: ${project.creativeBrief.musicStyle}`,
      project.creativeBrief.songStory && `The song tells: ${project.creativeBrief.songStory}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'quick_video') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonists: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `Place: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Action or dialogue: ${project.creativeBrief.action}`,
      `Format: ${project.creativeBrief.quickFormat}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'trailer') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonists: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `World and locations: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Trailer conflict and promise: ${project.creativeBrief.action}`,
      `Target trailer duration: ${project.creativeBrief.durationSeconds}s`,
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

export function musicPromptLimit(model: string | undefined): number {
  return catalogEntry(model)?.promptLimit ?? REMOTE_PROMPT_LIMIT
}

export function musicRequiresLyricSections(model: string | undefined): boolean {
  const family = catalogEntry(model)?.family
  return family === 'minimax_remote' || family === 'minimax_music3'
}

export function compiledMusicCuePrompt(cue: Pick<StoryMusicCue, 'style'>, model: string | undefined): string {
  return cue.style.trim().slice(0, musicPromptLimit(model))
}

export function musicRequestTitleKey(model: string | undefined): 'music.aceRequest' | 'music.minimaxLocalRequest' | 'music.minimaxRequest' {
  const family = catalogEntry(model)?.family
  if (family === 'ace_step') return 'music.aceRequest'
  if (family === 'minimax_music3') return 'music.minimaxLocalRequest'
  return 'music.minimaxRequest'
}

export type MusicCueBlock =
  | { key: 'notice.reviewPromptFirst'; params: { title: string } }
  | { key: 'notice.reviewPromptAndLyricsFirst'; params: { title: string } }
  | { key: 'music.promptOverLimit'; params: { count: number; limit: number; title: string } }
  | { key: 'notice.needsSectionTags'; params: { title: string } }

export function musicCueBlock(cue: StoryMusicCue, model: string | undefined): MusicCueBlock | null {
  const style = cue.style.trim()
  if (!style) {
    return {
      key: cue.instrumental ? 'notice.reviewPromptFirst' : 'notice.reviewPromptAndLyricsFirst',
      params: { title: cue.title },
    }
  }
  if (!cue.instrumental && !cue.lyrics.trim()) {
    return { key: 'notice.reviewPromptAndLyricsFirst', params: { title: cue.title } }
  }
  const limit = musicPromptLimit(model)
  if (style.length > limit) {
    return { key: 'music.promptOverLimit', params: { count: style.length, limit, title: cue.title } }
  }
  if (!cue.instrumental && musicRequiresLyricSections(model) && !MINIMAX_LYRIC_SECTION.test(cue.lyrics)) {
    return { key: 'notice.needsSectionTags', params: { title: cue.title } }
  }
  return null
}

export function miniMaxCuePayload(cue: StoryMusicCue, model: StoryProject['music']['model']): string {
  return JSON.stringify({
    model,
    prompt: compiledMusicCuePrompt(cue, model),
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
