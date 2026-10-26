import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { LinearFilter, LinearMipmapLinearFilter, Texture } from 'three'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { COMIC_GUTTER, COMIC_PAD, COMIC_PAGE_RIM, chooseComicLayout, isFrameAspect, paintComicPage } from '../src/features/scene3d/comicLayout.ts'
import { projectPoint } from '../src/features/scene3d/camera.ts'
import {
  COMIC_CUTOUT_AHEAD,
  COMIC_DURATION,
  COMIC_FOV,
  COMIC_FPS,
  COMIC_HOLD,
  COMIC_METERS_PER_PIXEL,
  COMIC_POP,
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
  comicCutoutSlide,
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

test('every page has the frame shape and the wide hold keeps the paper in frame', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    const aspect = format === 'portrait' ? 9 / 16 : 16 / 9
    for (const count of [3, 4, 5, 6]) {
      for (const seed of [0, 1]) {
        const layout = chooseComicLayout(format, count, seed, 0, count - 1)
        const err = Math.abs(layout.pageW / layout.pageH / aspect - 1)
        assert.ok(err <= 0.06, `${format} ${count} seed ${seed} aspect ${layout.pageW}x${layout.pageH}`)
        for (const cell of layout.cells) assert.equal(isFrameAspect(format, cell.w, cell.h), cell.hero, `${format} ${count}`)
        const varied = layout.cells.filter(cell => !cell.hero).map(cell => cell.w / cell.h)
        assert.equal(new Set(varied.map(value => value.toFixed(2))).size, varied.length, `${format} ${count} repeats a cell`)
        const pair = buildComicPair({
          format, seed, fromPanel: 0, toPanel: count - 1,
          panels: Array.from({ length: count }, () => ({ url: 'panel.png' })),
        })
        const pose = comicCameraAt(pair.exit, comicFrameSeconds(comicFrameCount() - 1))
        const pageW = layout.pageW * COMIC_METERS_PER_PIXEL
        const pageH = layout.pageH * COMIC_METERS_PER_PIXEL
        const frame = pair.exit.width / pair.exit.height
        assertPaper(format, pose, pageW, pageH, frame, `${format} ${count} seed ${seed}`)
      }
    }
  }
})

function assertPaper(
  format: 'landscape' | 'portrait',
  pose: { eye: [number, number, number]; look: [number, number, number]; fov: number },
  pageW: number, pageH: number, frame: number, label: string,
) {
  const hit = (x: number, y: number) => {
    const point = projectPoint([x, y, 0], pose.eye, pose.look, pose.fov, frame)
    assert.ok(point, label)
    return point
  }
  for (const [x, y] of [[-pageW / 2, 0], [pageW / 2, 0], [-pageW / 2, pageH], [pageW / 2, pageH]] as const) {
    const point = hit(x, y)
    assert.ok(point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1, `${label} clips`)
  }
  const rim = COMIC_PAGE_RIM * COMIC_METERS_PER_PIXEL
  const paper = [
    hit(-pageW / 2 + rim, rim), hit(pageW / 2 - rim, rim),
    hit(-pageW / 2 + rim, pageH - rim), hit(pageW / 2 - rim, pageH - rim),
  ]
  const span = format === 'landscape'
    ? Math.max(...paper.map(point => point.x)) - Math.min(...paper.map(point => point.x))
    : Math.max(...paper.map(point => point.y)) - Math.min(...paper.map(point => point.y))
  assert.ok(span >= 0.85, `${label} covers ${span}`)
}

function overlaps(cells: { x: number; y: number; w: number; h: number }[]) {
  return cells.some((cell, index) => cells.slice(index + 1).some(other =>
    cell.x < other.x + other.w && other.x < cell.x + cell.w && cell.y < other.y + other.h && other.y < cell.y + cell.h))
}

test('cells and gutters cover the padded paper and nothing larger than a gutter is empty', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    for (const count of [3, 4, 5, 6]) {
      for (const seed of [0, 1]) {
        assertTiled(chooseComicLayout(format, count, seed, 0, count - 1), `${format} ${count} seed ${seed}`)
      }
    }
  }
})

function assertTiled(layout: ReturnType<typeof chooseComicLayout>, label: string) {
  const origin = COMIC_PAGE_RIM + COMIC_PAD
  const width = layout.pageW - origin * 2
  const height = layout.pageH - origin * 2
  const mask = new Uint8Array(width * height)
  for (const cell of layout.cells) {
    const x0 = cell.x - origin
    const y0 = cell.y - origin
    assert.ok(x0 >= 0 && y0 >= 0 && x0 + cell.w <= width && y0 + cell.h <= height, `${label} outside`)
    for (let y = 0; y < cell.h; y += 1) {
      const row = (y0 + y) * width + x0
      for (let x = 0; x < cell.w; x += 1) {
        assert.equal(mask[row + x], 0, `${label} overlap`)
        mask[row + x] = 1
      }
    }
  }
  const dist = chebyshev(mask, width, height, true)
  const half = COMIC_GUTTER / 2
  const spine = new Uint8Array(mask.length)
  for (let i = 0; i < mask.length; i += 1) {
    if (mask[i]) continue
    assert.ok(dist[i] <= half, `${label} gap ${dist[i]}`)
    if (dist[i] >= half) spine[i] = 1
  }
  const spineDist = chebyshev(spine, width, height, false)
  for (let i = 0; i < mask.length; i += 1) {
    if (!mask[i]) assert.ok(spineDist[i] <= half, `${label} hairline`)
  }
}

function chebyshev(source: Uint8Array, width: number, height: number, zerosAreNear: boolean): Int16Array {
  const dist = new Int16Array(source.length)
  dist.fill(width + height)
  for (let i = 0; i < source.length; i += 1) if (zerosAreNear ? source[i] : source[i]) dist[i] = 0
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = y * width + x
      let best = dist[i]
      if (x > 0) best = Math.min(best, dist[i - 1] + 1)
      if (y > 0) best = Math.min(best, dist[i - width] + 1, x > 0 ? dist[i - width - 1] + 1 : best, x + 1 < width ? dist[i - width + 1] + 1 : best)
      dist[i] = best
    }
  }
  for (let y = height - 1; y >= 0; y -= 1) {
    for (let x = width - 1; x >= 0; x -= 1) {
      const i = y * width + x
      let best = dist[i]
      if (x + 1 < width) best = Math.min(best, dist[i + 1] + 1)
      if (y + 1 < height) best = Math.min(best, dist[i + width] + 1, x > 0 ? dist[i + width - 1] + 1 : best, x + 1 < width ? dist[i + width + 1] + 1 : best)
      dist[i] = best
    }
  }
  return dist
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
    assert.ok(Math.abs(factor - (1 - COMIC_CUTOUT_AHEAD / distance)) < 1e-9, 'scale is (D - d) / D')
    assert.ok(Math.abs(matched.scale - from.scale * factor) < 1e-9)
    close(matched.position, placed.position, `${format} compensated cutout`)
    const host = pair.exit.slots.find(slot => slot.id === 'panel-1')!
    const hostCell = comicPagePixels(format).cells[1]
    const body = { x: host.position[0], y: host.position[1], z: host.position[2], scale: host.scale, aspect: hostCell.w / hostCell.h }
    const poppedPlace = comicCutoutPlacement(body, true, { pose: exitWide, aspect: size.width / size.height })
    assert.ok(popped.scale > comicCutoutPlacement(body, false).scale, 'one filler cutout breaks the border')
    close(popped.position, poppedPlace.position, `${format} popped cutout`)
    assert.equal(matched.position[2], from.position[2] + COMIC_CUTOUT_AHEAD)
    const centerY = from.position[1] + from.scale
    assert.ok(Math.abs(matched.position[1] + matched.scale - centerY) < 1e-9, 'scaled about the fill axis')
  }
})

function projectedSpan(x: number, y: number, z: number, halfW: number, pose: { eye: readonly number[]; look: readonly number[]; fov: number }, aspect: number) {
  const left = projectPoint([x - halfW, y, z], pose.eye as [number, number, number], pose.look as [number, number, number], pose.fov, aspect)
  const right = projectPoint([x + halfW, y, z], pose.eye as [number, number, number], pose.look as [number, number, number], pose.fov, aspect)
  assert.ok(left && right, 'panel edges project')
  return Math.hypot(right.x - left.x, right.y - left.y)
}

test('a cutout slides four to six percent of its panel and the pop still reads larger', () => {
  for (const format of ['landscape', 'portrait'] as const) {
    const pair = buildComicPair({ format })
    const frame = comicCatalogueSize(format)
    const aspect = frame.width / frame.height
    const last = comicFrameSeconds(comicFrameCount() - 1)
    const fill = comicCameraAt(pair.exit, 0)
    const wide = comicCameraAt(pair.exit, last)
    const panelSlot = pair.exit.slots.find(slot => slot.id === 'panel-0')!
    const cell = comicPagePixels(format).cells[0]
    const panel = {
      x: panelSlot.position[0], y: panelSlot.position[1], z: panelSlot.position[2],
      scale: panelSlot.scale, aspect: cell.w / cell.h,
    }
    const slide = comicCutoutSlide(panel, fill, wide, aspect)
    assert.ok(slide >= 0.04 && slide <= 0.06, `${format} slide ${slide}`)
    const host = pair.exit.slots.find(slot => slot.id === 'panel-1')!
    const popped = pair.exit.slots.find(slot => slot.id === 'cutout-1')!
    const hostAspect = comicPagePixels(format).cells[1].w / comicPagePixels(format).cells[1].h
    const base = projectedSpan(host.position[0], host.position[1] + host.scale, host.position[2], host.scale * hostAspect, wide, aspect)
    const grown = projectedSpan(popped.position[0], popped.position[1] + popped.scale, popped.position[2], popped.scale * hostAspect, wide, aspect)
    assert.ok(Math.abs(grown / base - COMIC_POP) < 1e-3, `${format} pop ${grown / base}`)
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
