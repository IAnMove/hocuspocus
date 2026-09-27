import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CUT_PAPER_CAST,
  CUT_PAPER_FORBIDDEN,
  CUT_PAPER_KIT_ID,
  CUT_PAPER_LOCATIONS,
  CUT_PAPER_PIECES,
  CUT_PAPER_TOWN,
} from '../src/features/cutPaper/bible.ts'
import { compileCutPaperPilotScene, compileCutPaperShot, CUT_PAPER_PILOT_DURATION, CUT_PAPER_PILOT_SCRIPT, CUT_PAPER_PILOT_SCRIPT_EN } from '../src/features/cutPaper/pilot.ts'
import { createTijeralCharacterKits, tijeralCharacterKitId, CUT_PAPER_TTS } from '../src/features/cutPaper/characterKits.ts'
import { createTijeralStoryProject, TIJERAL_STORY_ID } from '../src/features/cutPaper/storyProject.ts'
import { normalizeStoryProject } from '../src/features/stories/model.ts'
import { assertCutPaperKitHasNoPrivateGlb, cutPaperKitManifest, cutPaperPuppetLayers } from '../src/features/cutPaper/puppet.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'
import { evaluateSceneLayer, normalizeSceneKeyframes, withSceneKeyframes } from '../src/lib/sceneTimeline.ts'

test('Tijeral kit ids are stable, original and not a private GLB body', () => {
  assert.equal(CUT_PAPER_KIT_ID, 'tijeral-cut-paper')
  assert.equal(CUT_PAPER_TOWN.id, 'tijeral')
  assert.equal(CUT_PAPER_CAST.length, 6)
  assert.equal(new Set(CUT_PAPER_CAST.map(item => item.id)).size, 6)
  assert.equal(CUT_PAPER_LOCATIONS.length, 5)
  assert.deepEqual([...CUT_PAPER_PIECES], ['legs', 'torso', 'arm-back', 'arm-front', 'head', 'face', 'hat'])
  assert.ok(CUT_PAPER_FORBIDDEN.some(item => item.includes('orange parka')))
  assert.equal(cutPaperKitManifest().characters.join(','), 'nilo,berta,kito,rami,paca,lino')
})

test('a puppet is one transparent body plus four independent mouths', () => {
  const layers = cutPaperPuppetLayers({ characterId: 'nilo', x: 40, y: 60, scale: 1 }, 8)
  const ids = layers.map(layer => layer.id)
  const body = layers.find(layer => layer.id === 'puppet-nilo')
  assert.equal(ids.filter(id => id === 'puppet-nilo').length, 1)
  assert.equal(body?.source.endsWith('nilo-body.png'), true)
  const mouths = layers.filter(layer => layer.faceBinding?.role === 'mouth')
  assert.equal(mouths.length, 4)
  assert.ok(mouths.every(layer => layer.faceBinding?.poseLayerId === 'puppet-nilo'))
  assert.ok(mouths.every(layer => layer.relationship?.targetLayerId === 'puppet-nilo'))
  assert.ok(mouths.every(layer => layer.source.includes('/mouths/paper-')))
  assert.equal(mouths.find(layer => layer.id === 'puppet-nilo-mouth-closed')?.transform.opacity, 0)
  assert.equal(mouths.find(layer => layer.id === 'puppet-nilo-mouth-wide')?.transform.opacity, 0)
  assert.ok(mouths.every(layer => layer.transform.scale < (body?.transform.scale ?? 0) * 0.4))
  assert.ok(mouths.every(layer => layer.transform.y < (body?.transform.y ?? 0)))
  assert.ok(layers.every(layer => layer.type !== 'model3d'))
  assert.throws(() => cutPaperPuppetLayers({ characterId: 'kenny', x: 0, y: 0, scale: 1 }, 1), /Unknown/)
})

test('pilot scene roundtrips, lasts 78s, talks, slides, and never mounts a GLB', () => {
  const scene = compileCutPaperPilotScene()
  assert.equal(scene.duration, CUT_PAPER_PILOT_DURATION)
  assert.equal(CUT_PAPER_PILOT_DURATION >= 60 && CUT_PAPER_PILOT_DURATION <= 90, true)
  assert.equal(scene.generationPolicy, 'provided_only')
  assert.equal(scene.layers.some(layer => layer.id === 'location-plaza'), true)
  assert.equal(scene.layers.some(layer => layer.id === 'puppet-kito'), true)
  assert.ok((scene.dialogueBeats?.length ?? 0) > CUT_PAPER_PILOT_SCRIPT.length)
  assert.ok(scene.dialogueBeats?.every(beat => beat.mouthLayerIds.length === 4 && beat.confidence === 'aligned-audio'))
  const niloFirst = scene.dialogueBeats?.filter(beat => beat.id.startsWith('nilo-1-')) ?? []
  assert.ok(niloFirst.length >= 10)
  assert.ok(Math.abs((niloFirst.at(-1)?.end ?? 0) - (6 + 4.44)) < 0.05)
  const kito = scene.layers.find(layer => layer.id === 'puppet-kito')
  const xs = (kito?.animation.keyframes ?? []).map(frame => frame.x)
  assert.ok(Math.min(...xs) < 60 && Math.max(...xs) > 100)
  assertCutPaperKitHasNoPrivateGlb(scene)
  const restored = parseSceneFile(serializeSceneFile(scene))
  assert.equal(restored.name, scene.name)
  assert.equal(restored.layers.length, scene.layers.length)
  assert.equal(restored.dialogueBeats?.length, scene.dialogueBeats?.length)
  assert.ok(restored.layers.every(layer => layer.type !== 'model3d' && !/\.glb/i.test(layer.source)))
})

test('Story Lab chapter roundtrips and each beat links to Video 2D', () => {
  const project = normalizeStoryProject(createTijeralStoryProject())
  assert.equal(project.id, TIJERAL_STORY_ID)
  assert.equal(project.language, 'Español')
  assert.equal(project.spokenLanguage, 'Español de España')
  assert.equal(project.beats.length, 3)
  assert.ok(project.beats.every(beat => beat.sceneLink?.editor === 'video2d' && beat.sceneLink.href.includes('/examples/cut-paper/shots/')))
  assert.equal(project.world.locations.length, 5)
  assert.equal(project.characters.length, 6)
  const plaza = compileCutPaperShot('plaza')
  const talk = compileCutPaperShot('talk')
  const sticker = compileCutPaperShot('sticker')
  assert.equal(plaza.duration, 6)
  assert.ok(talk.dialogueBeats?.length)
  assert.ok(talk.dialogueBeats?.every(beat => beat.end - beat.start <= 2.5 || beat.id.startsWith('nilo-1') || beat.id.startsWith('nilo-2')))
  const kitoTalk = sticker.dialogueBeats ?? []
  assert.ok(kitoTalk.length >= 3)
  assert.ok(Math.abs((kitoTalk[0]?.start ?? 0) - 10) < 0.05)
  assert.ok((kitoTalk.at(-1)?.end ?? 0) < 11.2)
  assert.ok(sticker.layers.some(layer => layer.id === 'puppet-kito'))
  assert.ok(parseSceneFile(serializeSceneFile(talk)).dialogueBeats?.length)
  assert.equal(plaza.layers.find(layer => layer.id === 'location-plaza')?.fill, true)
  assert.ok(project.characters.every(character => character.characterKitRef?.id.startsWith('tijeral-') && character.characterKitRef.workspace === 'default'))
  const talkEn = compileCutPaperShot('talk', 'en')
  assert.equal(talkEn.audioTracks?.[0]?.filename, 'vo-nilo-nilo-1-en.wav')
  assert.ok(talkEn.dialogueBeats?.some(beat => /fountain|frozen/i.test(beat.text)))
  assert.equal(CUT_PAPER_PILOT_SCRIPT_EN.length, CUT_PAPER_PILOT_SCRIPT.length)
  const niloWide = talk.layers.find(layer => layer.id === 'puppet-nilo-mouth-wide')
  const niloClosed = talk.layers.find(layer => layer.id === 'puppet-nilo-mouth-closed')
  const bertaWide = talk.layers.find(layer => layer.id === 'puppet-berta-mouth-wide')
  const kitoWide = sticker.layers.find(layer => layer.id === 'puppet-kito-mouth-wide')
  assert.equal(evaluateSceneLayer(niloClosed, 1).opacity, 1)
  assert.equal(evaluateSceneLayer(niloWide, 1).opacity, 0)
  assert.equal(evaluateSceneLayer(niloWide, 6.05).opacity, 1)
  assert.equal(evaluateSceneLayer(bertaWide, 1).opacity, 0)
  assert.equal(evaluateSceneLayer(kitoWide, 1).opacity, 0)
})

test('Tijeral character kits are 2D cutouts with Qwen voices and optional bodies', () => {
  const kits = createTijeralCharacterKits()
  assert.equal(kits.length, 6)
  assert.deepEqual(kits.map(kit => kit.id), CUT_PAPER_CAST.map(item => tijeralCharacterKitId(item.id)))
  const nilo = kits.find(kit => kit.id === 'tijeral-nilo')
  const rami = kits.find(kit => kit.id === 'tijeral-rami')
  assert.equal(nilo?.style, 'cutout')
  assert.equal(nilo?.voice?.voiceId, CUT_PAPER_TTS.nilo.voiceId)
  assert.ok(nilo?.base?.source.endsWith('nilo-body.png'))
  assert.equal(nilo?.mouth.wide?.kind, 'overlay')
  assert.ok(nilo?.identityReference?.source.includes('nilo-canonical'))
  assert.equal(nilo?.speech3d, undefined)
  assert.equal(rami?.base, undefined)
  assert.equal(rami?.voice?.voiceId, CUT_PAPER_TTS.rami.voiceId)
  assert.equal(new Set(kits.map(kit => kit.voice?.voiceId)).size, 6)
})

function animatorImportedDuration(scene: ReturnType<typeof compileCutPaperShot>): number {
  const ends = scene.layers.map(layer => {
    const frames = normalizeSceneKeyframes(layer.animation.keyframes, layer)
    if (!frames) return layer.animation.duration
    return withSceneKeyframes(layer, frames, layer.animation.duration).animation.duration
  })
  return Math.min(3600, Math.max(0.1, scene.duration, ...ends))
}

test('Video 2D beats stay inside their shot duration after Scene Animator import', () => {
  const shots = [
    ['plaza', 6],
    ['talk', 40],
    ['sticker', 26],
  ] as const
  for (const [id, duration] of shots) {
    const scene = compileCutPaperShot(id)
    const restored = parseSceneFile(serializeSceneFile(scene))
    assert.equal(scene.duration, duration)
    assert.ok(scene.layers.every(layer => (layer.animation.keyframes ?? []).every(frame => frame.time <= duration + 1e-6)))
    assert.ok(scene.layers.every(layer => layer.animation.duration <= duration + 1e-6))
    assert.equal(animatorImportedDuration(restored), duration)
  }
  const ice = compileCutPaperShot('plaza').layers.find(layer => layer.id === 'sticker-ice')
  assert.ok((ice?.animation.keyframes ?? []).every(frame => (frame.opacity ?? 1) > 0.5))
})
