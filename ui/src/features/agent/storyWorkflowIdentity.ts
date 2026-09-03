import type {
  AgentAction,
  AgentConfigureStorySongAction,
} from './agentActions'

export interface ConfiguredStorySongIdentity {
  targetStoryId: string
  targetStoryTitle: string
  cueId: string
  cueTitle: string
  candidateId?: string
  configuration: AgentConfigureStorySongAction
}

export function bindGeneratedSongCandidate(
  configured: ConfiguredStorySongIdentity | null,
  candidateId: string,
): ConfiguredStorySongIdentity | null {
  return configured && candidateId ? { ...configured, candidateId } : configured
}

/** Bind dependent same-turn actions to identities returned by earlier steps. */
export function bindStoryWorkflowAction(
  action: AgentAction,
  context: {
    createdStoryId: string
    createdStoryTitle: string
    configuredSong: ConfiguredStorySongIdentity | null
    stagedProductionId: string
  },
): AgentAction {
  if (context.createdStoryId && action.type === 'configure_story_song' && !action.targetStoryId) {
    return { ...action, targetStoryId: context.createdStoryId, targetStoryTitle: context.createdStoryTitle }
  }
  if (context.configuredSong && action.type === 'generate_story_song') {
    const song = context.configuredSong
    return { ...action, targetStoryId: song.targetStoryId, targetStoryTitle: song.targetStoryTitle, cueId: song.cueId, cueTitle: song.cueTitle }
  }
  if (context.configuredSong && action.type === 'stage_story_music_video') {
    const song = context.configuredSong
    return {
      ...action,
      targetStoryId: song.targetStoryId,
      targetStoryTitle: song.targetStoryTitle,
      cueId: song.cueId,
      cueTitle: song.cueTitle,
      ...(song.candidateId ? { candidateId: song.candidateId } : {}),
      songName: '',
    }
  }
  if (context.stagedProductionId && action.type === 'start_director_production') {
    return { ...action, productionId: context.stagedProductionId }
  }
  return action
}
