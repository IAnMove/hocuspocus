import { createFilledComic, generateComicPanelArtwork, generateFilledComicArtwork } from './actions'
import type { CreateComicCommand, GenerateComicCommand } from './commands'

export async function create(command: CreateComicCommand) {
  return createFilledComic(command)
}

export async function generate(command: GenerateComicCommand, expectedProjectId?: string) {
  return generateFilledComicArtwork(command, undefined, expectedProjectId)
}

export async function generatePanel(pageNumber: number, panelNumber: number) {
  return generateComicPanelArtwork(pageNumber, panelNumber)
}
