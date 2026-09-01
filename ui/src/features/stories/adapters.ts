import {
  applyStoredStoryProposal,
  approveStorySection,
  approveStoryVisuals,
  configureStorySong,
  createFilledStory,
  generateStorySectionDraft,
  generateStorySong,
  generateStoryVisuals,
  stageStoryComic,
  stageStoryMusicVideo,
  stageStoryVideo,
  startDirectorProduction,
  updateFilledStory,
} from './actions'
import type {
  ApplyStoryProposalCommand,
  ApproveStorySectionCommand,
  ApproveStoryVisualsCommand,
  ConfigureStorySongCommand,
  CreateStoryCommand,
  GenerateStorySectionCommand,
  GenerateStorySongCommand,
  GenerateStoryVisualsCommand,
  StageStoryComicCommand,
  StageStoryMusicVideoCommand,
  StageStoryVideoCommand,
  StartDirectorProductionCommand,
  UpdateStoryCommand,
} from './commands'

export async function create(command: CreateStoryCommand) {
  return createFilledStory(command)
}

export async function update(command: UpdateStoryCommand) {
  return updateFilledStory(command)
}

export async function generateProposal(command: GenerateStorySectionCommand, onStep?: (message: string) => void) {
  return generateStorySectionDraft(command, onStep)
}

export async function applyProposal(command: ApplyStoryProposalCommand) {
  return applyStoredStoryProposal(command)
}

export async function approveSection(command: ApproveStorySectionCommand) {
  return approveStorySection(command)
}

export async function approveVisuals(command: ApproveStoryVisualsCommand) {
  return approveStoryVisuals(command)
}

export async function generateVisuals(command: GenerateStoryVisualsCommand) {
  return generateStoryVisuals(command)
}

export async function configureSong(command: ConfigureStorySongCommand) {
  return configureStorySong(command)
}

export async function generateSong(command: GenerateStorySongCommand) {
  return generateStorySong(command)
}

export async function stageComic(command: StageStoryComicCommand) {
  return stageStoryComic(command)
}

export async function stageVideo(command: StageStoryVideoCommand) {
  return stageStoryVideo(command)
}

export async function stageMusicVideo(command: StageStoryMusicVideoCommand) {
  return stageStoryMusicVideo(command)
}

export async function startProduction(command: StartDirectorProductionCommand) {
  return startDirectorProduction(command)
}
