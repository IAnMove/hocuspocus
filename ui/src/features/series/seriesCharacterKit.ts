import { createCharacterKit, type CharacterKit } from '../../lib/characterKit'
import { randomUuid } from '../../lib/uuid'
import { seriesEntityImage } from './shotReferences'
import { seriesAssetUrl } from './referenceImages'
import type { SeriesCharacter, SeriesProject } from './types'

/** A new library identity is bound by id on save, never guessed from a character name. */
export function seriesCharacterKit(workspace: string, series: SeriesProject, character: SeriesCharacter, existing?: CharacterKit) {
  const kit = existing ? { ...existing } : { ...createCharacterKit(character.name), id: randomUuid(), lookNotes: character.appearance }
  if (kit.base) return kit
  const image = seriesEntityImage(character, series.assets)
  if (image) {
    kit.base = { id: `${kit.id}-base`, name: character.name, source: seriesAssetUrl(image), kind: 'image',
      alphaStatus: 'unknown', reviewState: character.approval === 'approved' ? 'approved' : 'pending', workspace }
    kit.identityReference ??= { ...kit.base }
  }
  kit.provenance = [...kit.provenance, { method: 'series-character-configuration', workspace, seriesId: series.id, characterId: character.id }]
  return kit
}
