import { createFilledComic, generateComicPanelArtwork, generateFilledComicArtwork } from './actions'
import type { CreateComicCommand, GenerateComicCommand } from './commands'

export async function create(command: CreateComicCommand) {
  return createFilledComic(command)
}

export async function generate(command: GenerateComicCommand, onProgress?: (message: string) => void) {
  return generateFilledComicArtwork(command, onProgress)
}

export async function generatePanel(pageNumber: number, panelNumber: number, onProgress?: (message: string) => void) {
  return generateComicPanelArtwork(pageNumber, panelNumber, onProgress)
}
