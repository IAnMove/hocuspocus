import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, mountCharacterKitLayers, type CharacterKit } from '../src/lib/characterKit'
import { acceptLipsCandidate, applyLipsPack, createLipsPack, lipsGenerationPrompt, missingLipsSounds } from '../src/lib/lipsCreator'
import { characterImageModels, preferredCharacterImageModel } from '../src/lib/characterImageModels'
import { CHARACTER_MOUTH_STATES, MOUTH_SOUND_GROUPS, mouthStateForSound, normalizeMouthMapping } from '../src/lib/characterMouthStates'
import { previewFaceRigDialogueFromCues } from '../src/lib/characterKitFaceRig'
import { rebuildCutoutDialogueLayers, type SceneDialogueBeat } from '../src/lib/cutoutDialogue'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile'
import { sampleMouthCues } from '../src/features/characters/sampleMouthCues'
import { speechPreparationReadiness } from '../src/lib/characterSpeechPreparation'
import type { ModelDef, Scene } from '../src/types'

function fullPack(): CharacterKit {
  const pack = createLipsPack('Lips')
  pack.base = { id: 'ref', name: 'Reference', source: '/reference.png', kind: 'image', alphaStatus: 'opaque', reviewState: 'approved' }
  pack.mouth = Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, {
    id: state, name: state, source: `/${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'approved', workspace: 'source-workspace',
  }]))
  return pack
}

test('description-only generation selects a text model and never asks for a reference', () => {
  const model = (id: string, extras: Partial<ModelDef> = {}): ModelDef => ({ model_type: id, architecture: id, name: id,
    family: 'qwen', is_downloaded: true, is_i2v: false, is_t2v: false, fps: 0, guidance_max_phases: 1, ...extras })
  const models = [model('qwen_image_edit_20b', { supports_ref_images: true }), model('qwen_image_21', { supports_ref_images: true }),
    model('qwen_image_21_bf16', { is_downloaded: false }), model('wan_t2v', { family: 'wan' })]
  const textModels = characterImageModels(models, false)
  assert.deepEqual(textModels.map(item => item.model_type), ['qwen_image_21'])
  assert.equal(preferredCharacterImageModel(textModels, false), 'qwen_image_21')
  assert.equal(preferredCharacterImageModel(characterImageModels(models, true), true), 'qwen_image_edit_20b')
  const pack = fullPack(); pack.lookNotes = 'Burgundy watercolor lips'
  const textPrompt = lipsGenerationPrompt(pack, 'wide', false)
  assert.match(textPrompt, /Burgundy watercolor lips/)
  assert.match(textPrompt, /entirely from the description/)
  assert.doesNotMatch(textPrompt, /Use the reference/)
  assert.match(lipsGenerationPrompt(pack, 'wide', true), /Use the reference/)
})

test('standard sound assignments remain compatible and overrides can share drawings', () => {
  assert.equal(mouthStateForSound('M'), 'pressed'); assert.equal(mouthStateForSound('U'), 'pucker')
  assert.equal(mouthStateForSound('A', { A: 'round' }), 'round')
  assert.deepEqual(normalizeMouthMapping({ A: 'round', U: 'round' }), { A: 'round', U: 'round' })
  assert.equal(normalizeMouthMapping({ A: 'unknown' }), undefined)
  assert.equal(normalizeMouthMapping({ Z: 'wide' }), undefined)
})

test('accepting one candidate preserves the original and every other mouth', () => {
  const pack = fullPack(), before = structuredClone(pack)
  const next = acceptLipsCandidate(pack, 'wide', { ...pack.mouth.wide!, id: 'new', source: '/new.png' })
  assert.deepEqual(pack, before)
  assert.equal(next.mouth.wide!.source, '/new.png')
  assert.equal(next.provenance.at(-1)!.previousSource, '/wide.png')
  for (const state of CHARACTER_MOUTH_STATES.filter(state => state !== 'wide')) assert.equal(next.mouth[state], pack.mouth[state])
  assert.throws(() => acceptLipsCandidate(pack, 'wide', { ...pack.mouth.wide!, alphaStatus: 'opaque' }), /background/)
  assert.equal(acceptLipsCandidate({ ...pack, mouthCandidates: { wide: next.mouth.wide } }, 'wide', next.mouth.wide!).mouthCandidates!.wide, undefined)
})

test('linking keeps actor identity and placement, and refuses unreviewed sound assignments', () => {
  const pack = fullPack(); pack.mouthMapping = { A: 'round' }
  const actor = { ...createCharacterKit('Actor'), base: { ...pack.base!, source: '/actor.png' }, lookNotes: 'Actor style', anchors: { base: { mouth: { offsetX: 1, offsetY: 2, scale: .08, rotation: 0 } } } }
  const linked = applyLipsPack(pack, actor)
  assert.equal(linked.id, actor.id); assert.equal(linked.base, actor.base); assert.equal(linked.anchors, actor.anchors)
  assert.equal(linked.lookNotes, actor.lookNotes); assert.equal(linked.mouth.wide!.workspace, 'source-workspace')
  assert.deepEqual(linked.mouthMapping, { A: 'round' })
  assert.throws(() => applyLipsPack({ ...pack, mouth: {} }, actor), /Approve/)
})

test('sample and actual voice preview use the same changed vowels and resting mouth', () => {
  const pack = fullPack(); pack.mouthMapping = { A: 'round', U: 'wide', rest: 'small' }
  const cues = [{ start: .2, end: .4, viseme: 'A' }, { start: .4, end: .7, viseme: 'U' }] as const
  assert.deepEqual(sampleMouthCues(cues, pack).map(cue => cue.sourceState), ['round', 'wide'])
  const preview = previewFaceRigDialogueFromCues(pack, 'A U', cues, 1)
  assert.deepEqual(preview.visemes.map(cue => cue.state), ['small', 'round', 'wide', 'small'])
})

test('custom assignments survive scene serialization and drive real mouth opacity including the tail', () => {
  const pack = fullPack(); pack.mouthMapping = { A: 'round', U: 'wide', rest: 'small' }
  const mounted = mountCharacterKitLayers(pack)
  assert.equal(mounted.find(layer => layer.faceBinding?.state === 'small')!.transform.opacity, 1)
  const beat: SceneDialogueBeat = { id: 'line', text: 'A U', start: 0, end: 1, audioTrackId: 'voice',
    mouthLayerIds: mounted.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id),
    lipSync: { version: 1, driver: 'phonetic', text: 'A U', audioTrackId: 'voice', filename: 'voice.wav', offset: 0, duration: 1,
      cues: [{ start: .2, end: .4, viseme: 'A' }, { start: .4, end: .7, viseme: 'U' }] } }
  const scene = { version: 1, width: 1280, height: 720, fps: 30, duration: 2, layers: mounted, dialogueBeats: [beat] } as Scene
  const restored = parseSceneFile(serializeSceneFile(scene))
  const layers = rebuildCutoutDialogueLayers(restored.layers, restored.dialogueBeats!, 30, 2)
  const at = (time: number) => layers.filter(layer => layer.faceBinding?.role === 'mouth' && evaluateSceneLayer(layer, time).opacity === 1).map(layer => layer.faceBinding!.state)
  assert.deepEqual(at(.3), ['round']); assert.deepEqual(at(.5), ['wide']); assert.deepEqual(at(1.5), ['small'])
})

test('a reduced collection can bind several sounds to the same approved mouth', () => {
  const pack = fullPack()
  pack.mouth = { closed: pack.mouth.closed, wide: pack.mouth.wide }
  pack.mouthMapping = Object.fromEntries(MOUTH_SOUND_GROUPS.map(sound => [sound, sound === 'rest' ? 'closed' : 'wide']))
  assert.deepEqual(missingLipsSounds(pack), [])
  assert.equal(speechPreparationReadiness(pack, 'base').complete, true)
})
