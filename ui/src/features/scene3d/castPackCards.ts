import type { CastPackCardCopy } from './castPacks.ts'
import { dialogueCard } from './dialogueTemplates.ts'
import { groupCard } from './groupTemplates.ts'
import { reactionCard } from './reactionTemplates.ts'
import { verticalCard } from './verticalTemplates.ts'

/** The packs built on `castPacks`, in the order a card is looked up. */
const CAST_PACK_CARDS: ReadonlyArray<(id: string, locale: 'en' | 'es') => CastPackCardCopy | undefined> = [
  dialogueCard, reactionCard, groupCard, verticalCard,
]

/** The authored copy (title, description, requirements) of a dialogue, reaction, group or vertical card; undefined for any other id. */
export function castPackCard(id: string, locale: 'en' | 'es' = 'en'): CastPackCardCopy | undefined {
  for (const card of CAST_PACK_CARDS) {
    const found = card(id, locale)
    if (found) return found
  }
  return undefined
}
