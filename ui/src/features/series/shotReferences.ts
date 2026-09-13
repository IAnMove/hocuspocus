import type { SeriesAsset, SeriesCharacter, SeriesEpisode, SeriesLocation, SeriesProject, SeriesShot } from './types'

export type SeriesReferenceRoom = 'characters' | 'locations'
export type SeriesReferenceState = 'ready' | 'missingEntity' | 'missingImage' | 'unapproved'

export function seriesEntityImage(entity: SeriesCharacter | SeriesLocation | undefined,
  assets: Record<string, SeriesAsset>, variantId?: string, approvedIds?: string[]) {
  const variants = entity && ('wardrobeVariants' in entity ? entity.wardrobeVariants : entity.variants)
  const ids = [
    ...(variants?.find(item => item.id === variantId)?.referenceAssetIds || []),
    ...(entity && 'primaryReferenceAssetId' in entity && entity.primaryReferenceAssetId ? [entity.primaryReferenceAssetId] : []),
    ...(entity?.referenceAssetIds || []),
  ]
  return ids.map(id => assets[id]).find(asset => asset && asset.uri?.trim() && !asset.isDerivedThumbnail
    && ['image', 'character', 'location', 'prop'].includes(asset.kind)
    && (!approvedIds || approvedIds.includes(asset.id)))
}

export function seriesShotReferences(series: SeriesProject, episode: SeriesEpisode, shot: SeriesShot) {
  const snapshot = episode.canonSnapshot || {}
  const characters = (snapshot.characters ?? series.characters) as SeriesCharacter[]
  const locations = (snapshot.locations ?? series.locations) as SeriesLocation[]
  const assets = (snapshot.assets ?? series.assets) as Record<string, SeriesAsset>
  const approvedIds = snapshot.approvedReferenceAssetIds as string[] | undefined
  const state = (entity: SeriesCharacter | SeriesLocation | undefined, asset: SeriesAsset | undefined): SeriesReferenceState =>
    !entity ? 'missingEntity' : !asset ? 'missingImage' : entity.approval !== 'approved' ? 'unapproved' : 'ready'
  const people = shot.visibleCharacterIds.map(id => {
    const character = characters.find(item => item.id === id)
    const asset = seriesEntityImage(character, assets, shot.wardrobeByCharacterId[id], approvedIds)
    return { id, name: character?.name || id, asset, state: state(character, asset) }
  })
  const location = locations.find(item => item.id === shot.locationId)
  const background = seriesEntityImage(location, assets, shot.locationVariantId, approvedIds)
  const locationState = state(location, background)
  return { people, background, location, locations, locationState,
    ready: locationState === 'ready' && people.every(person => person.state === 'ready') }
}
