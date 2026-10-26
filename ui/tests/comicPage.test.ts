import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { LinearFilter, LinearMipmapLinearFilter, Texture } from 'three'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { chooseComicLayout, isFrameAspect, paintComicPage } from '../src/features/scene3d/comicLayout.ts'
import {
  COMIC_DURATION,
  COMIC_FOV,
  COMIC_FPS,
  COMIC_HOLD,
  COMIC_TEMPLATE_IDS,
  COMIC_YAW_ARC,
  COMIC_YAW_DEG,
  applyComicTemplate,
  buildComicPair,
  comicCameraAt,
  comicCard,
  comicCatalogueSize,
  comicFrameCount,
  comicFrameSeconds,
  comicFramingProgress,
  comicMoveWindow,
  comicCutoutPlacement,
  comicPagePixels,
  comicWidePose,
  cutoutFactor,
  fillFrameOffset,
} from '../src/features/scene3d/comicPage.ts'
import { comicMontageBody, comicTransitionBody } from '../src/features/scene3d/comicTransition.ts'
import { imageCutoutMesh } from '../src/features/scene3d/imageCutout.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { templateTraits } from '../src/features/scene3d/templateTraits.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))

function close(a: readonly number[], b: readonly number[], label: string) {
  assert.equal(a.length, b.length, label)
  for (let i = 0; i < a.length; i += 1) assert.ok(Math.abs(a[i] - b[i]) < 1e-6, `${label} [${a}] vs [${b}]`)
}

function pngSize(name: string): [number, number, number] {
  const buf = readFileSync(join(HERE, '../public/scene3d/comic', name))
  assert.equal(buf[0], 0x89)
  return [buf.readUInt32BE(16), buf.readUInt32BE(20), buf[25]]
}

test('the layout keeps the cut panels at the frame aspect', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    for (const count of [3, 4, 5, 6]) {
      const first = chooseComicLayout(format, count, 0, 0, count - 1)
      const second = chooseComicLayout(format, count, 1, 0, count - 1)
      assert.notDeepEqual(first.cells.map(cell => [cell.w, cell.h]), second.cells.map(cell => [cell.w, cell.h]), `${format} ${count}`)
      assert.deepEqual(first, chooseComicLayout(format, count, 2, 0, count - 1))
      for (const layout of [first, second]) {
        const heroes = layout.cells.flatMap((cell, index) => cell.hero ? [index] : [])
        assert.deepEqual(heroes, [0, count - 1])
        layout.cells.forEach(cell => assert.equal(isFrameAspect(format, cell.w, cell.h), cell.hero))
        assert.equal(overlaps(layout.cells), false, `${format} ${count}`)
      }
    }
  }
  const moved = chooseComicLayout('landscape', 5, 0, 2, 4)
  assert.deepEqual(moved.cells.flatMap((cell, index) => cell.hero ? [index] : []), [2, 4])
  assert.throws(() => chooseComicLayout('landscape', 2, 0, 0, 1), /panel_count/)
  assert.throws(() => chooseComicLayout('landscape', 7, 0, 0, 1), /panel_count/)
  const painted = paintComicPage(chooseComicLayout('landscape', 4, 0, 0, 3))
  assert.ok(painted[0] < 40, 'the page rim is a dark vignette')
  assert.ok(painted.length > 1000)
  assert.equal(fillFrameOffset(COMIC_FOV), 1 / Math.tan((COMIC_FOV * Math.PI) / 360))
})

function overlaps(cells: { x: number; y: number; w: number; h: number }[]) {
  return cells.some((cell, index) => cells.slice(index + 1).some(other =>
    cell.x < other.x + other.w && other.x < cell.x + cell.w && cell.y < other.y + other.h && other.y < cell.y + cell.h))
}

test('filler pictures match the catalogue page and each cutout keeps an alpha channel', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    const px = comicPagePixels(format)
    assert.deepEqual(pngSize(`page-${format}.png`).slice(0, 2), [px.pageW, px.pageH])
    px.cells.forEach((cell, index) => {
      const [w, h, kind] = pngSize(`panel-${format}-${index}.png`)
      assert.deepEqual([w, h, kind], [cell.w, cell.h, 6])
      const cutout = pngSize(`cutout-${format}-${index}.png`)
      assert.deepEqual(cutout.slice(0, 2), [cell.w, cell.h])
      assert.equal(cutout[2], 6)
    })
  }
})

test('exit and enter share one wide pose and each end fills its panel', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    const pair = buildComicPair({ format })
    const size = comicCatalogueSize(format)
    const last = comicFrameSeconds(comicFrameCount() - 1)
    for (const doc of [pair.exit, pair.enter]) {
      assert.equal(doc.width, size.width)
      assert.equal(doc.height, size.height)
      assert.equal(doc.fps, COMIC_FPS)
      assert.equal(doc.duration, COMIC_DURATION)
      assert.equal(doc.camera.family, 'establishment')
      assert.equal(doc.camera.framing?.ease, 'smooth')
      assert.equal(doc.camera.framing?.yawArc, COMIC_YAW_ARC)
      const move = comicMoveWindow(doc.templateId.includes('enter') ? 'enter' : 'exit')
      assert.equal(doc.camera.framing?.moveStart, move.moveStart)
      assert.equal(doc.camera.framing?.moveEnd, move.moveEnd)
      assert.equal(doc.look?.toneMapping, 'none')
      assert.equal(doc.look?.exposure, 0)
      assert.equal(doc.environment, undefined)
      assert.equal(doc.screenBackdrop, undefined)
      assert.equal(doc.slots.filter(slot => slot.slot !== 'prop').length, 0)
      assert.ok(doc.slots.every(slot => slot.imageLook?.unlit === true && slot.imageLook.sharp === true && !slot.imageLook.tint))
      const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
      assert.ok(parsed)
      assert.equal(parsed!.camera.framing?.yawArc, COMIC_YAW_ARC)
      assert.ok(parsed!.slots.every(slot => slot.imageLook?.sharp === true && slot.imageLook.unlit === true))
    }
    assert.equal(comicFramingProgress(pair.exit, 0), 0)
    assert.equal(comicFramingProgress(pair.enter, last), 1)
    const wide = comicWidePose(format, size.width / size.height)
    const exitWide = comicCameraAt(pair.exit, last)
    const enterWide = comicCameraAt(pair.enter, 0)
    close(exitWide.eye, wide.eye, `${format} exit wide eye`)
    close(exitWide.look, wide.look, `${format} exit wide look`)
    close(enterWide.eye, wide.eye, `${format} enter wide eye`)
    close(enterWide.look, wide.look, `${format} enter wide look`)
    assert.equal(exitWide.fov, COMIC_FOV)
    close(exitWide.eye, enterWide.eye, `${format} shared wide eye`)
    close(exitWide.look, enterWide.look, `${format} shared wide look`)
    const yaw = (COMIC_YAW_DEG * Math.PI) / 180
    assert.ok(Math.abs(exitWide.eye[0] - Math.sin(yaw) * exitWide.eye[2] / Math.cos(yaw)) < 1e-6, `${format} wide yaw`)
    const exitFill = comicCameraAt(pair.exit, 0)
    const enterFill = comicCameraAt(pair.enter, last)
    const exitMove = comicMoveWindow('exit')
    const midU = (exitMove.moveStart + exitMove.moveEnd) / 2
    const mid = comicCameraAt(pair.exit, midU * COMIC_DURATION)
    const straight = exitFill.eye.map((value, index) => value + (exitWide.eye[index] - value) * 0.5)
    const bowed = Math.hypot(mid.eye[0] - straight[0], mid.eye[1] - straight[1], mid.eye[2] - straight[2])
    assert.ok(bowed > 0.01, `${format} yaw arc ${bowed}`)
    const flat = buildComicPair({ format, yawArc: 0 })
    const flatMid = comicCameraAt(flat.exit, midU * COMIC_DURATION)
    const flatBow = Math.hypot(flatMid.eye[0] - straight[0], flatMid.eye[1] - straight[1], flatMid.eye[2] - straight[2])
    assert.ok(flatBow < 1e-6, `${format} a zero arc stays on the straight path`)
    assert.ok(Math.abs(COMIC_HOLD - 0.4) < 1e-9)
    const from = pair.exit.slots.find(slot => slot.id === 'panel-0')!
    const to = pair.enter.slots.find(slot => slot.id === 'panel-3')!
    close(exitFill.look, [from.position[0], from.position[1] + from.scale, from.position[2]], 'exit fill look')
    close(enterFill.look, [to.position[0], to.position[1] + to.scale, to.position[2]], 'enter fill look')
    const distance = from.scale * fillFrameOffset(COMIC_FOV)
    assert.ok(Math.abs(exitFill.eye[2] - exitFill.look[2] - distance) < 1e-6)
    assert.ok(Math.abs(enterFill.eye[2] - enterFill.look[2] - to.scale * fillFrameOffset(COMIC_FOV)) < 1e-9)
    assert.deepEqual(pair.exit.slots.filter(slot => slot.id.startsWith('cutout')).map(slot => slot.id), ['cutout-0', 'cutout-1', 'cutout-2', 'cutout-3'])
    const matched = pair.exit.slots.find(slot => slot.id === 'cutout-0')!
    const popped = pair.exit.slots.find(slot => slot.id === 'cutout-1')!
    const factor = cutoutFactor(from.scale)
    const placed = comicCutoutPlacement({
      x: from.position[0], y: from.position[1], z: from.position[2], scale: from.scale,
      aspect: format === 'portrait' ? 9 / 16 : 16 / 9,
    }, false)
    assert.ok(Math.abs(factor - (1 - 0.04 / distance)) < 1e-9, 'scale is (D - d) / D')
    assert.ok(Math.abs(matched.scale - from.scale * factor) < 1e-9)
    close(matched.position, placed.position, `${format} compensated cutout`)
    const host = pair.exit.slots.find(slot => slot.id === 'panel-1')!
    const hostCell = comicPagePixels(format).cells[1]
    const body = { x: host.position[0], y: host.position[1], z: host.position[2], scale: host.scale, aspect: hostCell.w / hostCell.h }
    const poppedPlace = comicCutoutPlacement(body, true)
    assert.ok(popped.scale > comicCutoutPlacement(body, false).scale, 'one filler cutout breaks the border')
    close(popped.position, poppedPlace.position, `${format} popped cutout`)
    assert.equal(matched.position[2], from.position[2] + 0.04)
    const centerY = from.position[1] + from.scale
    assert.ok(Math.abs(matched.position[1] + matched.scale - centerY) < 1e-9, 'scaled about the fill axis')
  }
})

test('the four comic templates are in the library, translated, and kind transition', () => {
  for (const id of COMIC_TEMPLATE_IDS) {
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.deepEqual(SCENE3D_TEMPLATES.find(item => item.id === id)?.tags, ['transition'])
    assert.equal(en.template[id].title, comicCard(id, 'en')?.title)
    assert.equal(es.template[id].title, comicCard(id, 'es')?.title)
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(applyComicTemplate(id)?.templateId, id)
    const traits = templateTraits(doc, { category: 'cinema', family: doc.camera.family })
    assert.equal(traits.kind, 'transition')
    assert.ok(traits.uses.includes('transition'), id)
  }
  assert.equal(applyComicTemplate('two-shot'), null)
})

test('the operation body is the shared command', () => {
  const body = comicTransitionBody({
    workspace: 'studio', format: 'portrait', fromPanel: 0, toPanel: 3, exportClips: true, intentId: 'comic-1',
    panels: ['a.png', { video: 'clip.mp4', at: 60 }, 'b.png', { image: 'c.png', cutout: 'hero.png' }],
  })
  assert.equal(body.operation, 'scene3d.comic.transition')
  assert.equal(body.version, 1)
  assert.equal(body.intent_id, 'comic-1')
  assert.equal(body.input.export, true)
  assert.equal(body.input.from_panel, 0)
  assert.equal(body.input.panels.length, 4)
})

test('the montage body names the cut and the mode', () => {
  const body = comicMontageBody({
    workspace: 'studio', file: 'song.montage.json', between: 0, mode: 'replace', intentId: 'comic-ui-1',
  })
  assert.equal(body.operation, 'scene3d.comic.transition')
  assert.equal(body.version, 1)
  assert.equal(body.intent_id, 'comic-ui-1')
  assert.equal(body.input.montage, 'song.montage.json')
  assert.equal(body.input.between, 0)
  assert.equal(body.input.mode, 'replace')
  assert.equal(body.input.export, true)
  assert.equal('panels' in body.input, false)
})

test('a sharp panel samples the source texels without mipmaps', () => {
  const sharp = new Texture({ width: 16, height: 9 })
  const plain = new Texture({ width: 16, height: 9 })
  const slot = {
    id: 'panel-0', slot: 'prop' as const, media: 'image' as const, surface: 'cutout' as const,
    sourceUrl: 'panel.png', clip: null, position: [0, 0, 0] as [number, number, number], rotationY: 0, scale: 1,
  }
  const sharpMesh = imageCutoutMesh({ ...slot, imageLook: { unlit: true, sharp: true } }, sharp)
  const plainMesh = imageCutoutMesh({ ...slot, id: 'page', imageLook: { unlit: true } }, plain)
  assert.equal(sharp.generateMipmaps, false)
  assert.equal(sharp.minFilter, LinearFilter)
  assert.equal(sharp.magFilter, LinearFilter)
  assert.equal(plain.minFilter, LinearMipmapLinearFilter)
  assert.equal(plain.generateMipmaps, true)
  sharpMesh.geometry.dispose()
  plainMesh.geometry.dispose()
  sharp.dispose()
  plain.dispose()
})
