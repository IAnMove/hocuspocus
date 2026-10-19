// The Stages shelf of the shot library: the server's stage-<mold> cards and their documents.
import { getWorld3DTemplate, type World3DLibraryCard } from '../../api/world3dWorkspace'
import { parseScene3DDocument } from './document.ts'
import type { Scene3DDocument } from './types.ts'

/** Thrown when the server's document is not a Video 3D document with a room. */
export const INVALID_STAGE_DOCUMENT = 'invalid_stage_document'

const documents = new Map<string, Promise<Scene3DDocument>>()

/** A stage's editable document, fetched once per workspace and id: its thumbnail and Open share the request. */
export function loadStageDocument(workspace: string, id: string): Promise<Scene3DDocument> {
  const key = `${workspace}/${id}`
  const cached = documents.get(key)
  if (cached) return cached
  const pending = getWorld3DTemplate(workspace, id).then(body => {
    const document = parseScene3DDocument(body.document)
    if (!document?.room) throw new Error(INVALID_STAGE_DOCUMENT)
    return document
  })
  documents.set(key, pending)
  // A failed request is not remembered, so the next look tries again.
  pending.catch(() => { if (documents.get(key) === pending) documents.delete(key) })
  return pending
}

export function stageTitle(card: World3DLibraryCard, locale: 'en' | 'es') {
  return (locale === 'es' ? card.titleEs : card.titleEn) || card.id
}

export function stageLine(card: World3DLibraryCard, locale: 'en' | 'es') {
  return (locale === 'es' ? card.lineEs : card.lineEn) || ''
}

/** Speaking marks: the two subject marks plus the extra ones a card lists as props. */
export function stageMarks(card: World3DLibraryCard) {
  return card.subjects + card.props
}

export function stageShape(card: World3DLibraryCard): 'interior' | 'exterior' {
  return card.setting === 'exterior' ? 'exterior' : 'interior'
}

/** The library search, applied to the stage cards as the built-in shelves apply it: one phrase in the card's text. */
export function filterStageCards(cards: readonly World3DLibraryCard[], query: string, locale: 'en' | 'es') {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return [...cards]
  return cards.filter(card => [stageTitle(card, locale), stageLine(card, locale), card.id, card.place ?? '', card.setting ?? '', ...card.cameras]
    .join(' ').toLocaleLowerCase().includes(needle))
}
