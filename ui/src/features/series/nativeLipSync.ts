import type { Scene } from '../../types'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'
import { mountCharacterKitLayers } from '../../lib/characterKit'
import { speechPreparationReadiness } from '../../lib/characterSpeechPreparation'
import { rebuildCutoutDialogueLayers } from '../../lib/cutoutDialogue'
import type { SeriesProject, SeriesShot } from './types'

export function seriesSpeakerKit(workspace: string, series: SeriesProject, characterId: string, library: CharacterKitLibrary) {
  const ref = series.characters.find(character => character.id === characterId)?.voiceProfile?.characterKitRef
  return ref?.workspace === workspace ? library.kits[ref.id] : undefined
}

function hasMouthPlacement(kit?: CharacterKit) {
  const anchor = kit?.anchors.base?.mouth
  return anchor && Object.values(anchor).every(Number.isFinite) && anchor.scale > 0
}

export function seriesLipSyncIssues(workspace: string, series: SeriesProject, shots: SeriesShot[], library: CharacterKitLibrary) {
  const issues = new Map<string, { id: string; name: string; reason: 'link' | 'pose' | 'mouths' | 'placement' | 'offscreen' }>()
  for (const shot of shots) for (const beat of shot.dialogueBeats) {
    const kit = seriesSpeakerKit(workspace, series, beat.characterId, library)
    const ready = kit && speechPreparationReadiness(kit, 'base')
    const reason = !shot.visibleCharacterIds.includes(beat.characterId) ? 'offscreen'
      : !kit ? 'link' : !ready?.poseApproved ? 'pose' : !ready.complete ? 'mouths' : !hasMouthPlacement(kit) ? 'placement' : undefined
    if (reason) issues.set(beat.characterId, { id: beat.characterId,
      name: series.characters.find(character => character.id === beat.characterId)?.name || beat.characterId, reason })
  }
  return [...issues.values()]
}

/** Only rendering inputs matter; saving unrelated voice/description fields does not stale a take. */
export function seriesLipSyncFingerprint(workspace: string, series: SeriesProject, shot: SeriesShot, library: CharacterKitLibrary) {
  return JSON.stringify([1, shot.dialogueBeats, [...new Set(shot.dialogueBeats.map(beat => beat.characterId))].sort().map(id => {
    const kit = seriesSpeakerKit(workspace, series, id, library)
    return [id, kit?.id, kit?.base, kit?.mouth, kit?.anchors.base]
  })])
}

/** Mount the saved base and mouths onto exact Series character IDs, preserving authored motion/audio. */
export function applySeriesLipSync(scene: Scene, workspace: string, series: SeriesProject, shot: SeriesShot,
  library: CharacterKitLibrary, bodySources: Record<string, string> = {}): Scene {
  const issues = seriesLipSyncIssues(workspace, series, [shot], library)
  if (issues.length) throw new Error(`Lip sync: ${issues.map(issue => `${issue.name} (${issue.reason})`).join(', ')}`)
  const speakers = new Set(shot.dialogueBeats.map(beat => beat.characterId))
  let layers = scene.layers.filter(layer => !(layer.faceBinding?.role === 'mouth' && speakers.has(layer.faceBinding.poseLayerId)))
  const mouths = new Map<string, string[]>()
  for (const id of speakers) {
    const body = layers.find(layer => layer.id === id)
    if (!body || body.type !== 'image') throw new Error(`The saved scene has no character layer for ${id}.`)
    const kit = seriesSpeakerKit(workspace, series, id, library)!
    // Validate face-patch provenance against the approved pose before using its transparent derivative.
    const mounted = mountCharacterKitLayers(kit, 'base', body.transform, scene.duration, scene)
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
    // Phrase durations are measured from audio; visemes use the editor's known-text planner.
    // Marking a whole phrase as word-aligned would hold one mouth for the entire line.
    return { ...beat, mouthLayerIds: mouths.get(line.characterId)!, confidence: 'known-text' as const }
  })
  return { ...scene, dialogueBeats,
    layers: rebuildCutoutDialogueLayers(layers, dialogueBeats, scene.fps || 30, scene.duration) }
}
