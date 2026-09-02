import type { CreativeCharacter } from '../../lib/labHelpers'
import type { LanguageIntent } from '../../lib/languageIntent'

export interface ComicPanelCommand {
  caption: string
  dialogue: string
  sfx: string
  scene?: string
}

export interface ComicPageCommand {
  title: string
  stage: string
  panels: ComicPanelCommand[]
}

export interface CreateComicCommand {
  title: string
  synopsis: string
  language: string
  styleName: string
  characters: CreativeCharacter[]
  panels: ComicPanelCommand[]
  pages: ComicPageCommand[]
  imageProvider: 'profile' | 'maestro' | 'minimax'
  imageModel: string
  factualBiography: boolean
  languageIntent?: LanguageIntent
}

export interface GenerateComicCommand {
  imageProvider: 'keep' | 'maestro' | 'minimax'
  imageModel: string
  scope: 'all' | 'missing' | 'failed'
  pages: number[]
  pilot: boolean
  biographyReview: boolean
  confirm: true
}

export interface GenerateComicPanelCommand {
  pageNumber: number
  panelNumber: number
  confirm: true
}
