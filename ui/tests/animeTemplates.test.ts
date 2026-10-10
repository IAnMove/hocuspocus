import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  ANIME_CATEGORIES,
  ANIME_TEMPLATE_IDS,
  animeAliases,
  animeAuthoredCueKinds,
  animeCard,
  applyAnimeTemplate,
  isAnimeTemplateId,
} from '../src/features/scene3d/animeTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates } from '../src/features/scene3d/templateFilters.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'
import { WORLD_SFX_KINDS } from '../src/features/sceneFx/world.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/animeTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const SCREEN_KINDS = new Set(FX_CATALOG.map(item => item.id))

test('nine anime shots are registered, tagged, translated and free of project assets', () => {
  assert.equal(ANIME_TEMPLATE_IDS.length, 9)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of ANIME_TEMPLATE_IDS) {
    assert.ok(isAnimeTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    const row = SCENE3D_TEMPLATES.find(item => item.id === id)
    assert.deepEqual(row?.tags, ['anime'], id)
    assert.equal(TEMPLATE_CATEGORIES[id], ANIME_CATEGORIES[id])
    assert.ok(['action', 'cinema'].includes(TEMPLATE_CATEGORIES[id]), id)
    assert.ok(en.template[id]?.title && en.template[id]?.description, id)
    assert.ok(es.template[id]?.title && es.template[id]?.description, id)
    assert.equal(en.template[id].title, animeCard(id, 'en')?.title)
    assert.notEqual(animeCard(id, 'es')?.title, undefined)
    assert.ok((animeCard(id, 'en')?.requirements.length ?? 0) >= 2, id)
  }
  assert.equal(en.category.anime, 'Anime')
  assert.equal(applyAnimeTemplate('two-shot'), null)
  const anime = filterScene3DTemplates({ category: 'anime', setting: 'all', query: '', locale: 'en', titleOf: id => id })
  assert.deepEqual(anime.map(item => item.id), [...ANIME_TEMPLATE_IDS])
})

test('every anime shot builds a valid 16:9 document and reopens unchanged', () => {
  for (const id of ANIME_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1920)
    assert.equal(doc.height, 1080)
    assert.equal(doc.fps, 24)
    assert.ok(doc.duration >= 2.5 && doc.duration <= 6, id)
    assert.equal(doc.environment?.floorStyle, 'none')
    assert.ok(doc.screenBackdrop, id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera)
    assert.deepEqual(reopened.screenBackdrop, doc.screenBackdrop)
    assert.deepEqual(reopened.sfx, doc.sfx)
    assert.equal(reopened.worldSfx?.length ?? 0, doc.worldSfx?.length ?? 0)
    const background = doc.slots.find(slot => slot.id === 'background')
    assert.equal(background?.surface, 'environment', `${id}: the optional plate sits under the backdrop`)
    const framing = doc.camera.framing
    if (framing) {
      assert.ok(doc.slots.some(slot => slot.id === framing.targetSlot), id)
      // A cutout mirrored with rotationY = π must keep the camera in front of it.
      assert.equal(framing.relativeToFacing, false, id)
      assert.notEqual(doc.camera.family, 'fixed', `${id}: the fixed family ignores framing`)
    }
    const vertical = applyAnimeTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 1080)
    assert.equal(vertical.height, 1920)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
})

test('anime shots are distinct compositions', () => {
  const prints = ANIME_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots, doc.dressing, doc.sfx])
  })
  assert.equal(new Set(prints).size, ANIME_TEMPLATE_IDS.length)
  const backdrops = ANIME_TEMPLATE_IDS.map(id => JSON.stringify(applyScene3DTemplate(id).screenBackdrop))
  assert.equal(new Set(backdrops).size, ANIME_TEMPLATE_IDS.length)
})

test('anime shots use only catalogued effects and keep every cue inside the shot', () => {
  for (const id of ANIME_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const authored = animeAuthoredCueKinds(id)
    for (const kind of [...authored.sfx, ...authored.backdrop]) assert.ok(SCREEN_KINDS.has(kind), `${id}: ${kind}`)
    for (const kind of authored.worldSfx) assert.ok(WORLD_SFX_KINDS.includes(kind), `${id}: ${kind}`)
    assert.equal(doc.sfx?.length ?? 0, authored.sfx.length, `${id}: no screen cue was dropped`)
    assert.equal(doc.worldSfx?.length ?? 0, authored.worldSfx.length, `${id}: no world cue was dropped`)
    assert.equal(doc.screenBackdrop?.sfx.length, authored.backdrop.length, `${id}: no backdrop cue was dropped`)
    const cues = [...(doc.sfx ?? []), ...(doc.worldSfx ?? []), ...(doc.screenBackdrop?.sfx ?? [])]
    for (const cue of cues) assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
    for (const shake of doc.camera.shake ?? []) assert.ok(shake.start >= 0 && shake.end <= doc.duration + 1e-9, `${id}: shake`)
    for (const flash of (doc.sfx ?? []).filter(cue => cue.kind === 'impact_flash' || cue.kind === 'impact_invert')) {
      const frames = (flash.end - flash.start) * doc.fps
      assert.ok(frames > 1.99 && frames < 4.01, `${id}: ${flash.id} lasts ${frames} frames`)
    }
  }
})

test('the fleet is four copies with one role, and one family binding fills them all', () => {
  const doc = applyScene3DTemplate('anime-fleet-approach')
  const ships = doc.slots.filter(slot => slot.media === 'model3d')
  assert.deepEqual(ships.map(slot => slot.id), ['vehicle_1', 'vehicle_2', 'vehicle_3', 'vehicle_4'])
  assert.equal(new Set(ships.map(slot => slot.slot)).size, 1)
  assert.equal(ships[0].slot, 'prop')
  assert.ok(ships.every(slot => slot.motion?.faceTravel && slot.motion.to[2] > slot.position[2]), 'they come toward the camera')
  const bound = applyAnimeTemplate('anime-fleet-approach', { roles: { vehicle: '/api/v1/file/ship.glb?workspace=w' } })!
  assert.ok(bound.slots.filter(slot => slot.media === 'model3d').every(slot => slot.sourceUrl === '/api/v1/file/ship.glb?workspace=w'))
  assert.equal(bound.slots.find(slot => slot.id === 'background')?.sourceUrl, '')
  const flyby = applyScene3DTemplate('anime-airship-flyby')
  assert.equal(flyby.camera.framing?.targetSlot, 'vehicle')
  assert.equal(flyby.slots.find(slot => slot.id === 'vehicle')?.media, 'model3d')
})

test('the clash lands where the two rushes cross, and the flash and shake start there', () => {
  const doc = applyScene3DTemplate('anime-sword-clash')
  const flash = (doc.sfx ?? []).find(cue => cue.kind === 'impact_flash')!
  const subject = doc.slots.find(slot => slot.id === 'subject')!
  const rival = doc.slots.find(slot => slot.id === 'rival')!
  const at = (seconds: number) => slotPoseAtTime(subject, seconds, doc.duration).position[0] - slotPoseAtTime(rival, seconds, doc.duration).position[0]
  assert.ok(Math.abs(at(flash.start)) < 0.1, `gap ${at(flash.start)}`)
  assert.ok(at(flash.start - 0.5) < -1 && at(flash.start + 0.5) > 1, 'they pass each other')
  assert.equal(doc.camera.shake?.[0].start, flash.start)
  assert.ok(doc.worldSfx?.some(cue => cue.kind === 'shockwave' && cue.start === flash.start))
})

test('cutout slots bind by id, alias or role and only the eyecatch draws an optional title', () => {
  for (const id of ANIME_TEMPLATE_IDS) {
    const aliases = animeAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyAnimeTemplate(id, { roles: { [lead]: '/api/v1/file/a.png?workspace=w' } })!
    assert.ok(bound.slots.some(slot => slot.sourceUrl === '/api/v1/file/a.png?workspace=w'), id)
    assert.equal(applyAnimeTemplate(id)?.texts, undefined, `${id}: no placeholder text by default`)
  }
  const titled = applyAnimeTemplate('anime-eyecatch', { text: 'NEXT' })!
  assert.equal(titled.texts?.[0].text, 'NEXT')
  assert.equal(applyAnimeTemplate('anime-face-off', { text: 'NEXT' })?.texts, undefined)
  const subject = applyScene3DTemplate('anime-impact-frame').slots.find(slot => slot.id === 'subject')!
  assert.equal(subject.media, 'image')
  assert.equal(subject.surface, 'cutout')
  assert.deepEqual(subject.imageLook, { unlit: true })
})
