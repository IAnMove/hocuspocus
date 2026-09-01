import {
  applySeriesPlan,
  assembleSeriesEpisode,
  commitSeriesCanonDelta,
  createFilledSeriesEpisode,
  generateSeriesPlan,
  renderSeriesShots,
  reviewSeriesAttempts,
  updateSeriesEpisode,
} from './actions'
import type {
  ApplySeriesPlanCommand,
  AssembleSeriesEpisodeCommand,
  CommitSeriesCanonCommand,
  CreateSeriesEpisodeCommand,
  GenerateSeriesPlanCommand,
  RenderSeriesShotsCommand,
  ReviewSeriesAttemptsCommand,
  UpdateSeriesEpisodeCommand,
} from './commands'

export async function createEpisode(command: CreateSeriesEpisodeCommand) {
  return createFilledSeriesEpisode(command)
}

export async function updateEpisode(command: UpdateSeriesEpisodeCommand) {
  return updateSeriesEpisode(command)
}

export async function generatePlan(command: GenerateSeriesPlanCommand) {
  return generateSeriesPlan(command)
}

export async function applyPlan(command: ApplySeriesPlanCommand) {
  return applySeriesPlan(command)
}

export async function renderShots(command: RenderSeriesShotsCommand) {
  return renderSeriesShots(command)
}

export async function reviewAttempts(command: ReviewSeriesAttemptsCommand) {
  return reviewSeriesAttempts(command)
}

export async function assembleEpisode(command: AssembleSeriesEpisodeCommand) {
  return assembleSeriesEpisode(command)
}

export async function commitCanon(command: CommitSeriesCanonCommand) {
  return commitSeriesCanonDelta(command)
}
