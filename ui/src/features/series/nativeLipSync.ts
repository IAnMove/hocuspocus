import type { Scene } from '../../types'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'
import { mountCharacterKitLayers } from '../../lib/characterKit'
import { speechPreparationReadiness } from '../../lib/characterSpeechPreparation'
import { usableCharacterAsset, type CharacterKitReviewPolicy } from '../../lib/characterKitReview'
import { rebuildCutoutDialogueLayers } from '../../lib/cutoutDialogue'
import { isFacePatchCompatible } from '../../lib/characterFacePatch'
import type { SeriesProject, SeriesShot } from './types'

export function seriesSpeakerKit(workspace: string, series: SeriesProject, characterId: string, library: CharacterKitLibrary) {
  const ref = series.characters.find(character => character.id === characterId)?.voiceProfile?.characterKitRef
  return ref?.workspace === workspace ? library.kits[ref.id] : undefined
}

function hasMouthPlacement(kit?: CharacterKit) {
  const anchor = kit?.anchors.base?.mouth
  return anchor && Object.values(anchor).every(Number.isFinite) && anchor.scale > 0
}

/** A listener only needs the saved rest pose, not four approved speech drawings. */
export function seriesRestKit(workspace: string, series: SeriesProject, id: string, library: CharacterKitLibrary,
  policy: CharacterKitReviewPolicy) {
  const kit = seriesSpeakerKit(workspace, series, id, library)
  return kit && usableCharacterAsset(kit.base, policy) && usableCharacterAsset(kit.mouth.closed, policy)
    && hasMouthPlacement(kit) && isFacePatchCompatible(kit.mouth.closed, 'base', kit.base?.source) ? kit : undefined
}

export function visibleSeriesSpeakers(shot: SeriesShot) {
  return [...new Set(shot.dialogueBeats.map(beat => beat.characterId))].filter(id => shot.visibleCharacterIds.includes(id))
}

function kitIssue(kit: CharacterKit | undefined, policy: CharacterKitReviewPolicy) {
  if (!kit) return 'link' as const
  const ready = speechPreparationReadiness(kit, 'base')
  if (!usableCharacterAsset(kit.base, policy)) return policy === 'saved-draft' ? 'savedPose' as const : 'pose' as const
  const mouthReady = ready.rows.every(row => row.status === 'approved' || (policy === 'saved-draft' && row.status === 'pending'))
  if (!mouthReady) return policy === 'saved-draft' ? 'savedMouths' as const : 'mouths' as const
  return hasMouthPlacement(kit) ? undefined : 'placement' as const
}

export function seriesLipSyncIssues(workspace: string, series: SeriesProject, shots: SeriesShot[], library: CharacterKitLibrary,
  policy: CharacterKitReviewPolicy = 'approved') {
  const issues = new Map<string, { id: string; name: string; reason: NonNullable<ReturnType<typeof kitIssue>> }>()
  for (const shot of shots) for (const id of visibleSeriesSpeakers(shot)) {
    const kit = seriesSpeakerKit(workspace, series, id, library)
    const reason = kitIssue(kit, policy)
    if (reason) issues.set(id, { id,
      name: series.characters.find(character => character.id === id)?.name || id, reason })
  }
  return [...issues.values()]
}

/** Only rendering inputs matter; saving unrelated voice/description fields does not stale a take. */
export function seriesLipSyncFingerprint(workspace: string, series: SeriesProject, shot: SeriesShot, library: CharacterKitLibrary) {
  const speakers = [...shot.visibleCharacterIds].sort()
  return JSON.stringify([3, shot.dialogueBeats, speakers, speakers.map(id => {
    const kit = seriesSpeakerKit(workspace, series, id, library)
    return [id, kit?.id, kit?.base, kit?.mouth, kit?.anchors.base]
  })])
}

/** Mount the saved base and mouths onto exact Series character IDs, preserving authored motion/audio. */
export function applySeriesLipSync(scene: Scene, workspace: string, series: SeriesProject, shot: SeriesShot,
  library: CharacterKitLibrary, bodySources: Record<string, string> = {}, policy: CharacterKitReviewPolicy = 'approved'): Scene {
  const issues = seriesLipSyncIssues(workspace, series, [shot], library, policy)
  if (issues.length) throw new Error(`Lip sync: ${issues.map(issue => `${issue.name} (${issue.reason})`).join(', ')}`)
  const mountedIds = shot.visibleCharacterIds.filter(id => seriesRestKit(workspace, series, id, library, policy))
  let layers = scene.layers.filter(layer => !(layer.faceBinding?.role === 'mouth' && mountedIds.includes(layer.faceBinding.poseLayerId)))
  const mouths = new Map<string, string[]>()
  for (const id of mountedIds) {
    const body = layers.find(layer => layer.id === id)
    if (!body || body.type !== 'image') throw new Error(`The saved scene has no character layer for ${id}.`)
    const kit = seriesSpeakerKit(workspace, series, id, library)!
    // Validate face-patch provenance before using the pose's transparent derivative.
    const mounted = mountCharacterKitLayers(kit, 'base', body.transform, scene.duration, scene, policy)
    const overlays = mounted.filter(layer => layer.faceBinding?.role === 'mouth').map((layer, index) => ({ ...layer,
      id: `series-${id}-mouth-${layer.faceBinding!.state}`, z: body.z + (index + 1) / 100,
      faceBinding: { ...layer.faceBinding!, poseLayerId: id }, relationship: { type: 'parent' as const, targetLayerId: id } }))
    layers = layers.map(layer => layer.id === id ? { ...layer, source: bodySources[id] || kit.base!.source } : layer)
    layers.push(...overlays)
    mouths.set(id, overlays.map(layer => layer.id))
  }
  const dialogueBeats = shot.dialogueBeats.map(line => {
    const beat = scene.dialogueBeats?.find(item => item.id === line.id)
    const track = scene.audioTracks?.find(item => item.id === beat?.audioTrackId)
    if (!beat || beat.text !== line.text || !track || track.prompt !== line.text) {
      throw new Error(`The saved audio does not match dialogue ${line.id}. Prepare its voice in the editor first.`)
    }
    // The batch analyzes the real recording after mounting. Keep existing cue provenance.
    // An offscreen line keeps its recorded audio and must not animate a visible listener.
    return { ...beat, mouthLayerIds: mouths.get(line.characterId) ?? [], confidence: 'known-text' as const }
  })
  return { ...scene, dialogueBeats,
    layers: rebuildCutoutDialogueLayers(layers, dialogueBeats, scene.fps || 30, scene.duration) }
}
