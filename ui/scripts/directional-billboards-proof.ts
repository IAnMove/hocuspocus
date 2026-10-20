// A real Chromium render, on the CPU, of 3D shots with directional 2D figures.
//
//   npx tsx --tsconfig tsconfig.app.json scripts/directional-billboards-proof.ts --out DIR
//
// It bundles the owned World3D renderer (the one the server exports with), serves a synthetic five-direction kit from memory and
// renders four shots: an 8 s camera orbit around three figures (one still, one that walks across, one that speaks) under a warm
// light; a close fixed shot of a figure that walks and stops to speak; the frames around a change of sheet, to see the crossfade;
// and a figure behind and another in front of a 3D column (a real GLB), to see the depth test. It checks the pixels against what
// `directionalView` chose: the colour of the sheet of each figure (tinted by the light), the side its nose is on, the badge that
// only a mirrored sheet shows (the kit's own `side_r` has none), the cell its pips light (the walk cycle), the mouth drawing of the
// cue (lip-sync on a sheet with a mouth, the pose on one without), the blend of a fade, where it stands, the row of its boots
// against the ground and what hides what. It writes one contact sheet per shot to `DIR/directional-<shot>.sheet.png` and prints
// one JSON line. A failed check exits 1.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from '../src/features/scene3d/camera.ts'
import { CROSSFADE_SECONDS, DirectionMemory, LIGHT_TINT, directionalView, lightTint, type Direction, type DirectionalSprite, type Drawn } from '../src/features/scene3d/directionalSprite.ts'
import { referenceEye, walkedSlot } from '../src/features/scene3d/directionalPaint.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from '../src/features/scene3d/types.ts'
import {
  BADGE, BLINK, BOOT, CELL, COLUMN, DIRECTION_ORDER, FEET, FIGURE, IDLE_CELLS, MOUTHS, NOSE, PIP, PIP_OFF, PIP_ON, POSE_TORSO, WALK_CELLS,
  boxGlb, floorPng, mouthPng, posePng, sheetPng, torsoColor,
} from './directionalProofKit.ts'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const WIDTH = 960, HEIGHT = 540
const WORKSPACE = 'proof'
const WEBGL_ARGS = ['--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
/** Torso top to boots over the figure height, in the synthetic cells (drawCell). */
const TORSO_SHARE = (CELL.height * FEET - 120) / (CELL.height * FIGURE)
const FADE_FRAME = 1 / 30

type Rgb = readonly [number, number, number]
type Cue = [number, number, string]
type Figure = { id: string; slot: string; heightM: number; at: readonly [number, number]; sprite: Partial<DirectionalSprite>; talk?: Cue[]; blinks?: number[] }
type Prop = { id: string; file: string; at: readonly [number, number]; heightM: number }
type Shot = {
  name: string; duration: number; camera: Scene3DDocument['camera']; figures: Figure[]; props?: Prop[]; columns: number
  light?: { color: string; intensity: number }; times: number[] | 'fade'
  /** Alpha (0-255) of the faint halo around every figure of the kit, as a keyed picture has. */
  halo?: number
}

/** Mouth anchors on the idle sheets that have a mouth (% of the cell's longer edge): front, three-quarter and side; the backs have none. */
type Anchor = { offsetX: number; offsetY: number; scale: number; rotation: number }
/** Where the eyes are on the same sheets: a blink is drawn there while the figure speaks. */
const EYE_ANCHORS: Partial<Record<Direction, Anchor>> = {
  front: { offsetX: 0, offsetY: -28.7, scale: 0.07, rotation: 0 }, front34: { offsetX: 3.8, offsetY: -28.7, scale: 0.07, rotation: 0 }, side: { offsetX: 7, offsetY: -28.7, scale: 0.07, rotation: 0 },
}
const MOUTH_ANCHORS: Partial<Record<Direction, Anchor>> = {
  front: { offsetX: 0, offsetY: -17.2, scale: 0.06, rotation: 0 }, front34: { offsetX: 6.9, offsetY: -17.2, scale: 0.06, rotation: 0 },
  side: { offsetX: 11.3, offsetY: -17.5, scale: 0.06, rotation: 0 },
}
const WARM = { color: '#ffc080', intensity: 1.0 }

const SHOTS: Shot[] = [
  { name: 'orbit', duration: 8, columns: 3, times: [0, 1, 2, 3, 4, 5, 6, 7, 8], light: WARM,
    camera: { family: 'orbit', eye: [0, 1.6, 4.2], look: [0, 1, 0], fov: 40, orbitRadius: 7, orbitHeight: 2, orbitTurns: 0.5 },
    figures: [
      { id: 'ana', slot: 'subject_1', heightM: 1.7, at: [0, 0], sprite: { heading: 0, lightTint: 0, speech: [[6.5, 7.5]] }, talk: [[6.5, 7.5, 'wide']] },
      { id: 'luis', slot: 'prop', heightM: 1.8, at: [-4.5, -2], sprite: { walk: { to: [4.5, -2], speed: 1.2, start: 0.25 } } },
      { id: 'eva', slot: 'prop', heightM: 1.5, at: [2.4, 1.2], sprite: { heading: 180, speech: [[4.2, 5.6]] }, talk: [[4.2, 4.9, 'wide'], [4.9, 5.6, 'round']], blinks: [5.0] },
    ] },
  { name: 'walk', duration: 6, columns: 4, times: [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 2.5],
    camera: { family: 'fixed', eye: [0, 1.3, 6.5], look: [0, 1, 0], fov: 40 },
    figures: [{ id: 'ana', slot: 'subject_1', heightM: 1.8, at: [-3, 0], sprite: { walk: { to: [3, 0], speed: 1.2, start: 0 }, speech: [[2, 3]] } }] },
  { name: 'fade', duration: 4, columns: 4, times: 'fade', halo: 40,
    camera: { family: 'fixed', eye: [0, 1.3, 6.5], look: [0, 1, 0], fov: 40 },
    figures: [{ id: 'ana', slot: 'subject_1', heightM: 1.8, at: [-3, 0], sprite: { walk: { to: [3, 0], speed: 1.2, start: 0 } } }] },
  { name: 'overlap', duration: 2, columns: 2, times: [0.5, 1.5], halo: 40,
    camera: { family: 'fixed', eye: [0, 1.3, 6.5], look: [0, 1, 0], fov: 40 },
    figures: [
      // Two pairs side by side at one depth, planes overlapping: the red one faces the camera, the purple one turns its back. In the first pair the purple
      // stands to the right of the red, in the second to its left, so whichever the renderer draws first, one of them is the back one.
      { id: 'a1', slot: 'subject_1', heightM: 1.7, at: [-1.8, 0], sprite: { heading: 0 } },
      { id: 'a2', slot: 'prop', heightM: 1.7, at: [-1.35, 0], sprite: { heading: 180 } },
      { id: 'b1', slot: 'prop', heightM: 1.7, at: [1.35, 0], sprite: { heading: 180 } },
      { id: 'b2', slot: 'prop', heightM: 1.7, at: [1.8, 0], sprite: { heading: 0 } },
    ] },
  { name: 'occlude', duration: 2, columns: 2, times: [0.5, 1.5],
    camera: { family: 'fixed', eye: [0, 1.3, 6.5], look: [0, 1, 0], fov: 40 },
    figures: [
      { id: 'ana', slot: 'subject_1', heightM: 1.7, at: [0, 0], sprite: { heading: 0 } },
      { id: 'eva', slot: 'prop', heightM: 1.7, at: [0.45, 3.2], sprite: { heading: 0 } },
    ],
    props: [{ id: 'column', file: 'column.glb', at: [0.38, 2.2], heightM: 2.4 }] },
]

const url = (name: string) => `/api/v1/file/${name}?workspace=${WORKSPACE}`

/** Every file the page asks for, by name, and the sheets as the server hands them to a scene (with the kit's own `side_r`). */
function kitFiles(halo = 0) {
  const files = new Map<string, Buffer>([['pose.png', posePng()], ['floor.png', floorPng()], ['column.glb', boxGlb(0.5, 0.5, COLUMN)]])
  for (const [state, color] of Object.entries(MOUTHS)) files.set(`mouth-${state}.png`, mouthPng(color))
  files.set('blink.png', mouthPng(BLINK))
  const sheets: DirectionalSprite['sheets'] = []
  const add = (motion: 'walk' | 'idle', dir: Direction, reversed: boolean) => {
    const count = motion === 'walk' ? WALK_CELLS : IDLE_CELLS
    const made = sheetPng(dir, motion, count, reversed, halo)
    const name = `${motion}-${dir}${reversed ? '_r' : ''}.png`
    files.set(name, made.png)
    const mouth = motion === 'idle' && !reversed ? MOUTH_ANCHORS[dir] : undefined
    const eyes = motion === 'idle' && !reversed ? EYE_ANCHORS[dir] : undefined
    const id = `${motion === 'walk' && dir === 'side' && !reversed ? 'walk-12' : `${motion}-${dir}`}${reversed ? '_r' : ''}`
    sheets.push({ id, motion, dir: (reversed ? `${dir}_r` : dir) as Direction, source: url(name), columns: made.columns, rows: made.rows, count, cell: { ...CELL },
      fps: motion === 'walk' ? 8 : 2, loop: motion === 'walk' ? 'loop' : 'pingpong', ...(mouth ? { mouth } : {}), ...(eyes ? { eyes } : {}) })
  }
  for (const motion of ['walk', 'idle'] as const) for (const dir of DIRECTION_ORDER) add(motion, dir, false)
  for (const motion of ['walk', 'idle'] as const) add(motion, 'side', true)
  return { files, sheets }
}

function talkBlock(figure: Figure) {
  const cues = (figure.talk ?? []).map(([start, end, state]) => ({ start, end, state }))
  return { base: url('pose.png'), mouths: Object.fromEntries(Object.keys(MOUTHS).map(state => [state, url(`mouth-${state}.png`)])),
    mouth: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 }, rest: 'closed', cues,
    ...(figure.blinks ? { blink: { source: url('blink.png'), anchor: { offsetX: 0, offsetY: -28.7, scale: 0.07, rotation: 0 } }, blinks: figure.blinks } : {}) }
}

function sceneDocument(shot: Shot, sheets: DirectionalSprite['sheets']): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  // The legacy look: no tone mapping, so a flat colour comes out as itself.
  delete document.look
  delete document.lighting
  document.width = WIDTH; document.height = HEIGHT; document.duration = shot.duration; document.camera = shot.camera
  if (shot.light) document.light = { ...document.light, ...shot.light }
  const floor: Scene3DSlot = { id: 'floor', slot: 'background', position: [0, 0.004, 0], rotationY: 0, scale: 8, sourceUrl: url('floor.png'), media: 'image', surface: 'floor', textureRepeat: 1, clip: null }
  const figures = shot.figures.map(figure => ({
    id: figure.id, slot: figure.slot as Scene3DSlot['slot'], position: [figure.at[0], 0, figure.at[1]] as Vec3, rotationY: 0, scale: figure.heightM / 2,
    sourceUrl: url('pose.png'), media: 'image' as const, surface: 'cutout' as const, grounded: true, billboard: true, clip: null,
    imageLook: { grounded: true, shadow: 0.5 },
    screen: { media: 'image', sourceUrl: url('pose.png'), directional: { sheets, ...figure.sprite }, ...(figure.talk ? { talk: talkBlock(figure) } : {}) },
  } as unknown as Scene3DSlot))
  const props = (shot.props ?? []).map(prop => ({
    id: prop.id, slot: 'prop' as const, position: [prop.at[0], 0, prop.at[1]] as Vec3, rotationY: 0, scale: prop.heightM / 1.7, sourceUrl: url(prop.file), media: 'model3d' as const, grounded: true, clip: null,
  } as Scene3DSlot))
  document.slots = [floor, ...props, ...figures]
  return document
}

type Rect = [number, number, number, number]
type Expectation = {
  id: string; drawn: Drawn; sheetId: string; dir: Direction; motion: string; mirror: boolean; frame: number | null; speaking: boolean; badge: boolean; left: boolean
  blend?: { mix: number; from: string; fromDrawn: Drawn }; rect: Rect; ground: [number, number]; headY: number; tint: Rgb; state: string | null; blink: boolean
}

const scale = (color: Rgb, tint: Rgb): Rgb => [0, 1, 2].map(index => Math.min(255, Math.round(color[index] * tint[index]))) as unknown as Rgb
const mean = (a: Rgb, b: Rgb, mix: number): Rgb => [0, 1, 2].map(index => a[index] * (1 - mix) + b[index] * mix) as unknown as Rgb

type Picked = { id: string; motion: string; dir: Direction; badge: boolean; pose: boolean; left: boolean }

function describe(sprite: DirectionalSprite, drawn: Drawn): Picked {
  if (drawn.kind === 'pose') return { id: 'pose', motion: 'pose', dir: 'front', badge: false, pose: true, left: false }
  const sheet = sprite.sheets[drawn.sheet]
  return { id: sheet.id ?? '', motion: sheet.motion, dir: sheet.dir, badge: ['side', 'front34'].includes(sheet.dir) && sheet.facing !== 'left', pose: false, left: sheet.facing === 'left' }
}

/** What the chooser picked for each figure at `t`, and where the figure is on the screen: the oracle of the pixels. */
function expectations(shot: Shot, document: Scene3DDocument, t: number, memory: DirectionMemory): Expectation[] {
  const posed = document.slots.map(slot => walkedSlot({ ...slot }, slot.position, t))
  const eye = cameraEyeAtTime(document.camera, t, document.duration, posed), look = cameraLookAtTime(document.camera, t, document.duration, posed)
  const eye0 = referenceEye(document)
  return posed.flatMap((slot, index) => {
    const sprite = slot.screen?.directional
    if (!sprite) return []
    const { view } = directionalView(sprite, { start: [document.slots[index].position[0], document.slots[index].position[2]], eye0, eye: [eye[0], eye[2]], t, memory, id: slot.id })
    const figure = shot.figures.find(item => item.id === slot.id)!
    const feet = projectPoint(slot.position, eye, look, document.camera.fov, WIDTH / HEIGHT)!
    const head = projectPoint([slot.position[0], slot.position[1] + figure.heightM, slot.position[2]], eye, look, document.camera.fov, WIDTH / HEIGHT)!
    const high = head.y * HEIGHT, low = feet.y * HEIGHT, span = low - high, half = span * 0.45
    const tint = lightTint(document.light.color, document.light.intensity, sprite.lightTint ?? LIGHT_TINT)
    const cue = (figure.talk ?? []).find(([start, end]) => t >= start && t < end)
    const picked = describe(sprite, view)
    return [{ id: slot.id, drawn: view, sheetId: picked.id, dir: picked.dir, motion: picked.motion, mirror: view.kind === 'sheet' && view.mirror, frame: view.kind === 'sheet' ? view.frame : null,
      speaking: view.kind === 'sheet' && view.speaking, badge: picked.badge, left: picked.left, tint, state: cue ? cue[2] : null,
      blink: (figure.blinks ?? []).some(start => t >= start && t < start + 0.11),
      ...(view.blend ? { blend: { mix: view.blend.mix, from: describe(sprite, view.blend.from).id, fromDrawn: view.blend.from } } : {}),
      rect: [Math.round(feet.x * WIDTH - half), Math.round(high - span * 0.3), Math.round(feet.x * WIDTH + half), Math.round(low + span * 0.06)] as Rect,
      ground: [feet.x * WIDTH, low] as [number, number], headY: high }]
  })
}

type Colors = { on: Rgb; off: Rgb; nose: Rgb; boot: Rgb; badge: Rgb; blink: Rgb; mouths: Record<string, Rgb> }
type Probe = { rect: Rect; palette: Record<string, Rgb>; colors: Colors }

/** The torso colour of a drawing, before the tint. */
function torsoOf(sprite: DirectionalSprite, drawn: Drawn): Rgb {
  if (drawn.kind === 'pose') return POSE_TORSO
  const sheet = sprite.sheets[drawn.sheet]
  return torsoColor(sheet.dir, sheet.motion)
}

/** The colours a figure is painted in under its tint: what the pixels of its rectangle are matched against. */
function probeOf(want: Expectation, sprite: DirectionalSprite): Probe {
  const palette: Record<string, Rgb> = { pose: scale(POSE_TORSO, want.tint) }
  for (const dir of DIRECTION_ORDER) for (const motion of ['walk', 'idle'] as const) palette[`${motion}-${dir}`] = scale(torsoColor(dir, motion), want.tint)
  if (want.blend) palette.blend = scale(mean(torsoOf(sprite, want.blend.fromDrawn), torsoOf(sprite, want.drawn), want.blend.mix), want.tint)
  return { rect: want.rect, palette, colors: { on: scale(PIP_ON, want.tint), off: scale(PIP_OFF, want.tint), nose: scale(NOSE, want.tint), boot: scale(BOOT, want.tint), badge: scale(BADGE, want.tint), blink: scale(BLINK, want.tint),
    mouths: Object.fromEntries(Object.entries(MOUTHS).map(([state, color]) => [state, scale(color, want.tint)])) } }
}

/** Runs in the page: the pixels of one frame measured against the rectangle and the colours of each figure. */
const MEASURE = `(async (dataUrl, probes, tolerance, pip) => {
  const image = new Image(); image.src = dataUrl; await image.decode()
  const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
  const context = canvas.getContext('2d', { willReadFrequently: true }); context.drawImage(image, 0, 0)
  const near = (r, g, b, c, limit = tolerance) => Math.abs(r - c[0]) <= limit && Math.abs(g - c[1]) <= limit && Math.abs(b - c[2]) <= limit
  return probes.map(({ rect, palette, colors }) => {
    const [x0, y0, x1, y1] = rect
    const left = Math.max(0, x0), top = Math.max(0, y0), width = Math.min(canvas.width, x1) - left, height = Math.min(canvas.height, y1) - top
    const data = context.getImageData(left, top, width, height).data
    const counts = {}, rows = {}, mouths = {}
    let noseX = 0, noseN = 0, bodyX = 0, bodyN = 0, bootRow = -1, onX = 0, onN = 0, minX = 1e9, maxX = -1, badge = 0, blink = 0
    for (let y = 0; y < height; y += 1) {
      let boots = 0
      for (let x = 0; x < width; x += 1) {
        const i = (y * width + x) * 4, r = data[i], g = data[i + 1], b = data[i + 2]
        if (near(r, g, b, colors.on, 4)) { onX += x; onN += 1; minX = Math.min(minX, x); maxX = Math.max(maxX, x); continue }
        if (near(r, g, b, colors.off, 4)) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); continue }
        if (near(r, g, b, colors.badge, 10)) badge += 1
        if (near(r, g, b, colors.blink, 10)) blink += 1
        for (const [state, color] of Object.entries(colors.mouths)) if (near(r, g, b, color, 10)) mouths[state] = (mouths[state] || 0) + 1
        let classed = false
        for (const [name, color] of Object.entries(palette)) if (near(r, g, b, color)) { counts[name] = (counts[name] || 0) + 1; (rows[name] = rows[name] || {})[y] = ((rows[name] || {})[y] || 0) + 1; bodyX += x; bodyN += 1; classed = true; break }
        if (!classed && near(r, g, b, colors.nose)) { noseX += x; noseN += 1 }
        if (near(r, g, b, colors.boot, 8)) boots += 1
      }
      if (boots >= 3) bootRow = y
    }
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || ['none', 0]
    const heavy = Object.entries(rows[best[0]] || {}).filter(([, n]) => n >= 6).map(([y]) => Number(y)).sort((a, b) => a - b)
    const extent = (pip.count - 1) * pip.pitch + pip.width, scale = (maxX - minX + 1) / extent
    const lit = onN && maxX > minX ? Math.round((onX / onN - minX - pip.width * scale / 2) / (pip.pitch * scale)) : null
    return { winner: best[0], pixels: best[1], counts, bodyCentre: bodyN ? left + bodyX / bodyN : null, noseCentre: noseN ? left + noseX / noseN : null,
      bootBottom: bootRow >= 0 ? top + bootRow : null, topRow: heavy.length ? top + heavy[0] : null, lit, badge, blink, mouths }
  })
})`

/** Runs in the page: what hides what behind and in front of a column. `behind` is the torso band of the figure behind it and `edge` the
 * screen x where the column starts; `front` the torso of the figure before it. The column is anything warmer than the floor. */
const OCCLUDE = `(async (dataUrl, behind, front, tolerance) => {
  const image = new Image(); image.src = dataUrl; await image.decode()
  const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
  const context = canvas.getContext('2d', { willReadFrequently: true }); context.drawImage(image, 0, 0)
  const near = (r, g, b, c) => Math.abs(r - c[0]) <= tolerance && Math.abs(g - c[1]) <= tolerance && Math.abs(b - c[2]) <= tolerance
  const scan = (box, color) => {
    const [x0, y0, x1, y1] = box, data = context.getImageData(x0, y0, x1 - x0, y1 - y0).data
    const found = { own: [], other: [], warm: 0 }
    for (let y = 0; y < y1 - y0; y += 1) for (let x = 0; x < x1 - x0; x += 1) {
      const i = (y * (x1 - x0) + x) * 4, r = data[i], g = data[i + 1], b = data[i + 2]
      if (near(r, g, b, color)) found.own.push(x0 + x); else { found.other.push(x0 + x); if (r > b + 8) found.warm += 1 }
    }
    return found
  }
  const back = scan(behind.box, behind.color), ahead = scan(front.box, front.color)
  return { behindVisible: back.own.filter(x => x < behind.edge - 3).length, behindHidden: back.own.filter(x => x > behind.edge + 3).length,
    column: back.other.filter(x => x > behind.edge + 3).length, frontOwn: ahead.own.length, frontOther: ahead.other.length, frontWarm: ahead.warm }
})`

/** Runs in the page: how many pixels of each colour there are in each box. */
const COUNT = `(async (dataUrl, boxes, tolerance) => {
  const image = new Image(); image.src = dataUrl; await image.decode()
  const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
  const context = canvas.getContext('2d', { willReadFrequently: true }); context.drawImage(image, 0, 0)
  return boxes.map(({ box, color }) => {
    const [x0, y0, x1, y1] = box, data = context.getImageData(x0, y0, x1 - x0, y1 - y0).data
    let found = 0
    for (let i = 0; i < data.length; i += 4) if (Math.abs(data[i] - color[0]) <= tolerance && Math.abs(data[i + 1] - color[1]) <= tolerance && Math.abs(data[i + 2] - color[2]) <= tolerance) found += 1
    return { found, total: (x1 - x0) * (y1 - y0) }
  })
})`

const COMPOSE = `(async (frames, columns, cell) => {
  const rows = Math.ceil(frames.length / columns)
  const sheet = document.createElement('canvas'); sheet.width = columns * cell.width; sheet.height = rows * cell.height
  const context = sheet.getContext('2d'); context.fillStyle = '#000'; context.fillRect(0, 0, sheet.width, sheet.height)
  for (const [index, frame] of frames.entries()) {
    const image = new Image(); image.src = frame.png; await image.decode()
    const x = (index % columns) * cell.width, y = Math.floor(index / columns) * cell.height
    context.drawImage(image, x, y, cell.width, cell.height)
    context.font = '13px monospace'; context.fillStyle = 'rgba(0,0,0,.7)'; context.fillRect(x, y, cell.width, 20 + 15 * frame.lines.length)
    context.fillStyle = '#fff'; context.fillText('t = ' + frame.t.toFixed(3) + ' s', x + 6, y + 14)
    frame.lines.forEach((line, row) => { context.fillText(line, x + 6, y + 30 + row * 15) })
  }
  return sheet.toDataURL('image/png')
})`

async function bundleRenderer(dir: string) {
  const { build } = await import('esbuild')
  const outfile = path.join(dir, 'owned-renderer.js')
  await build({ entryPoints: [path.join(uiRoot, 'src/features/scene3d/ownedRenderer.tsx')], bundle: true, format: 'iife', platform: 'browser', target: 'es2022', outfile,
    logLevel: 'error', absWorkingDir: uiRoot, tsconfig: path.join(uiRoot, 'tsconfig.app.json'), loader: { '.css': 'empty' },
    define: { 'import.meta.env': '{"DEV":false,"PROD":true,"MODE":"production","BASE_URL":"/"}', 'process.env.NODE_ENV': '"production"' } })
  return fs.readFileSync(outfile, 'utf8')
}

const argAfter = (args: string[], flag: string) => { const at = args.indexOf(flag); return at >= 0 ? args[at + 1] : undefined }

type Measured = { winner: string; pixels: number; counts: Record<string, number>; bodyCentre: number | null; noseCentre: number | null; bootBottom: number | null; topRow: number | null; lit: number | null; badge: number; blink: number; mouths: Record<string, number> }
type Page = import('playwright').Page
type Renderer = { load: (d: unknown, s: unknown) => Promise<void>; frame: (s: number) => Promise<string>; dispose: () => void }

const overlap = (a: Rect, b: Rect) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]
const inside = (rect: Rect) => rect[0] >= 0 && rect[1] >= 0 && rect[2] <= WIDTH && rect[3] <= HEIGHT
const central = (want: Expectation) => Math.abs(want.ground[0] - WIDTH / 2) < WIDTH * 0.35 && want.ground[1] < HEIGHT - 6
/** The palette name of a sheet id: `walk-12` and the reversed sheets are drawn in the colour of their direction. */
const paletteName = (want: Expectation) => `${want.motion}-${want.dir}`

/** The colour the pixels should be: the blend while it fades, the old picture on the frame of the change, else the drawing. */
function expectedWinner(want: Expectation, sprite: DirectionalSprite): string {
  if (want.blend && want.blend.mix > 0) return 'blend'
  const drawn = want.blend ? want.blend.fromDrawn : want.drawn
  if (drawn.kind === 'pose') return 'pose'
  const sheet = sprite.sheets[drawn.sheet]
  return `${sheet.motion}-${sheet.dir}`
}

function nosePlace(want: Expectation, got: Measured): string | null {
  if (want.motion === 'pose' || !['side', 'front34'].includes(want.dir) || got.noseCentre === null || got.bodyCentre === null || want.blend) return null
  // A sheet that looks right shows its nose on the right unless it is mirrored; the kit's own left-looking sheet shows it on the left, unmirrored.
  const looksRight = want.left === want.mirror
  return (got.noseCentre > got.bodyCentre) === looksRight ? null : `the nose is on the ${looksRight ? 'left' : 'right'} but the figure looks ${looksRight ? 'right' : 'left'} (${want.sheetId}${want.mirror ? ' mirrored' : ''})`
}

function faceFailures(want: Expectation, got: Measured): string[] {
  const failures: string[] = []
  if (!want.blend && want.motion !== 'pose' && ['side', 'front34'].includes(want.dir) && (got.badge >= 8) !== want.badge) {
    failures.push(`the badge is ${got.badge >= 8 ? 'there' : 'missing'} on ${want.sheetId}${want.mirror ? ' mirrored' : ''}; the kit's side_r has none and a sheet that looks right has it`)
  }
  if (want.speaking && want.state) {
    if ((got.mouths[want.state] ?? 0) < 3) failures.push(`${want.sheetId} speaks but the ${want.state} mouth is not on it (${JSON.stringify(got.mouths)})`)
    for (const other of Object.keys(MOUTHS).filter(state => state !== want.state && state !== 'closed')) if ((got.mouths[other] ?? 0) >= 3) failures.push(`the ${other} mouth is on it at the cue of ${want.state}`)
    if (want.blink && got.blink < 3) failures.push(`${want.sheetId} blinks but the blink drawing is not on it`)
  } else if (!want.blend && want.motion !== 'pose' && ['wide', 'round'].some(state => (got.mouths[state] ?? 0) >= 3)) failures.push(`a mouth is drawn on a figure that is not speaking ${JSON.stringify(got.mouths)}`)
  return failures
}

function placeFailures(want: Expectation, got: Measured): string[] {
  const failures: string[] = []
  // A figure off the middle of a wide lens leans (the plane faces the camera, not the view): the further out, the more it may sit off its feet.
  const allowed = 8 + 0.06 * Math.abs(want.ground[0] - WIDTH / 2)
  if (got.bodyCentre !== null && Math.abs(got.bodyCentre - want.ground[0]) > allowed) failures.push(`stands at x ${got.bodyCentre.toFixed(0)}, should be ${want.ground[0].toFixed(0)}`)
  if (got.bootBottom === null) failures.push('no boots found')
  else if (Math.abs(got.bootBottom - want.ground[1]) > 4) failures.push(`boots end at row ${got.bootBottom}, the ground under the figure is row ${want.ground[1].toFixed(1)}`)
  if (got.topRow !== null && want.motion !== 'pose' && !want.blend) {
    const ratio = (want.ground[1] - got.topRow) / (want.ground[1] - want.headY)
    if (ratio < TORSO_SHARE - 0.07 || ratio > TORSO_SHARE + 0.06) failures.push(`the torso reaches ${(ratio * 100).toFixed(0)} % of the figure height, not about ${(TORSO_SHARE * 100).toFixed(0)} %`)
  }
  return failures
}

/** The checks of one figure in one frame; a figure that is clipped by the frame or covered by another is not judged. */
function judge(t: number, want: Expectation, got: Measured, others: Expectation[], sprite: DirectionalSprite): { failures: string[]; judged: boolean } {
  if (!inside(want.rect) || others.some(other => other !== want && overlap(want.rect, other.rect))) return { failures: [], judged: false }
  const failures: string[] = []
  const expected = expectedWinner(want, sprite)
  if (got.winner !== expected) failures.push(`drew ${got.winner}, the chooser asked for ${expected} (${paletteName(want)})`)
  const nose = nosePlace(want, got)
  if (nose) failures.push(nose)
  failures.push(...faceFailures(want, got))
  if (want.frame !== null && want.motion === 'walk' && !want.mirror && !want.blend && got.lit !== want.frame) failures.push(`lit cell ${got.lit}, the walk is at cell ${want.frame}`)
  if (central(want)) failures.push(...placeFailures(want, got))
  return { failures: failures.map(text => `t=${t.toFixed(3)} ${want.id}: ${text}`), judged: true }
}

async function openPage(browser: import('playwright').Browser, files: Map<string, Buffer>, bundle: string, problems: string[]): Promise<Page> {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } })
  page.on('pageerror', error => problems.push(`page error: ${error.message}`))
  page.on('console', message => { if (message.type() === 'error') problems.push(`console error: ${message.text().slice(0, 400)}`) })
  await page.route('http://hp.local/**', async route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop() ?? '')
    const body = files.get(name)
    if (body) await route.fulfill({ status: 200, contentType: name.endsWith('.glb') ? 'model/gltf-binary' : 'image/png', body })
    else await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><html><body style="margin:0"><div id="root"></div></body></html>' })
  })
  await page.goto('http://hp.local/')
  await page.addScriptTag({ content: bundle })
  return page
}

/** The frame before the first change of drawing of the walker, found as the renderer will meet it: frame by frame from the first paint. */
function fadeStart(shot: Shot, document: Scene3DDocument): number {
  const memory = new DirectionMemory()
  expectations(shot, document, 0, memory)
  for (let step = 1; step <= shot.duration * 30; step += 1) if (expectations(shot, document, step / 30, memory)[0].blend) return step - 1
  throw new Error('the walker never changes drawing')
}

/** The fade lasts CROSSFADE_SECONDS, a frame at a time, and starts on the old picture. */
function fadeFailures(report: { figures: { fade?: number }[] }[]): string[] {
  const mixes = report.map(frame => frame.figures[0].fade).filter((mix): mix is number => mix !== undefined)
  const wanted = Math.ceil(CROSSFADE_SECONDS / FADE_FRAME - 1e-9)
  return mixes.length === wanted && mixes[0] === 0 && mixes.every((mix, index) => index === 0 || mix > mixes[index - 1]) ? [] : [`the fade is ${JSON.stringify(mixes)}, expected ${wanted} rising mixes from 0`]
}

/** Where the column starts on the screen: the left-most of its eight corners. */
function columnEdge(prop: Prop, document: Scene3DDocument, t: number): number {
  const eye = cameraEyeAtTime(document.camera, t, document.duration, document.slots), look = cameraLookAtTime(document.camera, t, document.duration, document.slots)
  const half = 0.5 * (prop.heightM / 1.7) / 2
  const corners = [-1, 1].flatMap(dx => [-1, 1].flatMap(dz => [0, prop.heightM].map(y => projectPoint([prop.at[0] + dx * half, y, prop.at[1] + dz * half], eye, look, document.camera.fov, WIDTH / HEIGHT)!.x * WIDTH)))
  return Math.min(...corners)
}

/** The body of a figure never thins while its sheet is swapped for another: at every frame of the fade, the pixels that are the old sheet, the new sheet or their blend
 * are at least 85 % of the fewer of the two when each stands alone. With an alpha cut of one half the two must live together without a flicker. */
function bodyFailures(report: { figures: { drew: string }[] }[], counts: Record<string, number>[]): string[] {
  const from = report[0].figures[0].drew, to = report[report.length - 1].figures[0].drew
  const floor = 0.85 * Math.min(counts[0][from] ?? 0, counts[counts.length - 1][to] ?? 0)
  const totals = counts.map(found => (found[from] ?? 0) + (found[to] ?? 0) + (found.blend ?? 0))
  return floor > 0 && totals.every(total => total >= floor) ? [] : [`the body thins during the fade: ${JSON.stringify(totals)} px, never under ${Math.round(floor)}`]
}

/** What the depth test does: the column hides the figure behind it and the figure in front hides the column. */
async function occlusionFailures(page: Page, png: string, want: Expectation[], shot: Shot, document: Scene3DDocument, t: number): Promise<string[]> {
  const [behind, front] = [want.find(item => item.id === 'ana')!, want.find(item => item.id === 'eva')!]
  const band = (item: Expectation, from: number, to: number, side: number): Rect => {
    const height = item.ground[1] - item.headY
    return [Math.round(item.ground[0] - side), Math.round(item.ground[1] - height * to), Math.round(item.ground[0] + side), Math.round(item.ground[1] - height * from)]
  }
  const color = (item: Expectation) => scale(torsoColor(item.dir, item.motion === 'walk' ? 'walk' : 'idle'), item.tint)
  const edge = columnEdge(shot.props![0], document, t)
  const result = await page.evaluate(`${OCCLUDE}(${JSON.stringify(png)}, ${JSON.stringify({ box: band(behind, 0.38, 0.6, 40), color: color(behind), edge })}, ${JSON.stringify({ box: band(front, 0.4, 0.55, 20), color: color(front) })}, 18)`) as
    { behindVisible: number; behindHidden: number; column: number; frontOwn: number; frontOther: number; frontWarm: number }
  const failures: string[] = []
  if (result.column < 100) failures.push(`the column is not in the frame (${result.column} px)`)
  if (result.behindVisible < 60) failures.push(`the figure behind the column is not seen on the free side (${result.behindVisible} px)`)
  if (result.behindHidden > 0) failures.push(`${result.behindHidden} px of the figure behind the column are painted over it: the sprite is not depth tested`)
  if (result.frontOther > 0) failures.push(`the figure in front of the column is cut by it (${result.frontOther} px of its torso are not its own, ${result.frontWarm} are the column's)`)
  return failures
}

/** The plane of a figure is its cell, wider than the figure, and a keyed picture has a faint alpha all over it. Where two figures stand side by side
 * at one depth with their planes overlapping, each must show its own torso whole: neither cut by the other's empty plane (which would write depth) nor washed
 * by its halo. Whichever the renderer draws first, the other is the one that suffers, so every figure of the shot is checked. */
async function overlapFailures(page: Page, png: string, want: Expectation[], t: number): Promise<string[]> {
  const color = (item: Expectation) => scale(torsoColor(item.dir, item.motion === 'walk' ? 'walk' : 'idle'), item.tint)
  const boxes = want.map(item => {
    const unit = (item.ground[1] - item.headY) / 1.7, high = item.ground[1] - (item.ground[1] - item.headY) * 0.6, low = item.ground[1] - (item.ground[1] - item.headY) * 0.38
    return { box: [Math.round(item.ground[0] - 0.1 * unit), Math.round(high), Math.round(item.ground[0] + 0.1 * unit), Math.round(low)] as Rect, color: color(item) }
  })
  const counts = await page.evaluate(`${COUNT}(${JSON.stringify(png)}, ${JSON.stringify(boxes)}, 18)`) as { found: number; total: number }[]
  return counts.flatMap((shown, index) => shown.found < shown.total * 0.9
    ? [`t=${t.toFixed(3)} ${want[index].id} shows its torso in only ${shown.found}/${shown.total} px: another figure's empty plane cuts or washes it`] : [])
}

const label = (item: Expectation) => `${item.id}: ${item.sheetId}${item.frame !== null ? `#${item.frame}` : ''}${item.mirror ? ' mirrored' : ''}${item.speaking ? ' speaks' : ''}${item.blend ? ` fade ${item.blend.mix.toFixed(2)} from ${item.blend.from}` : ''}`

async function proveShot(page: Page, shot: Shot, raw: Scene3DDocument, out: string) {
  await page.evaluate(async ([doc, size]) => { await (window as unknown as { __world3dExport: Renderer }).__world3dExport.load(doc, size) }, [raw, { width: WIDTH, height: HEIGHT, fps: 30 }] as const)
  // The oracle reads the document as the editor does (`side_r` is a sheet that looks left), the renderer was given the raw one.
  const document = parseScene3DDocument(JSON.parse(JSON.stringify(raw)))!
  // A fade is met frame by frame from the first paint, so the frames before it are rendered too (and not judged).
  const start = shot.times === 'fade' ? fadeStart(shot, document) : 0
  const warmUp = Array.from({ length: Math.max(0, start - 1) }, (_unused, index) => (index + 1) / 30)
  const times = shot.times === 'fade' ? Array.from({ length: 8 }, (_unused, index) => (start + index) / 30) : shot.times
  const frames: { t: number; png: string; lines: string[] }[] = [], failures: string[] = [], report: { figures: { fade?: number }[] }[] = []
  let judged = 0
  const fadeCounts: Record<string, number>[] = []
  // The renderer holds a figure's sector from frame to frame; the oracle follows the same frames in the same order.
  const memory = new DirectionMemory()
  expectations(shot, document, 0, memory)   // the first paint of the stage, before the first frame
  for (const t of warmUp) {
    await page.evaluate(async seconds => (window as unknown as { __world3dExport: Renderer }).__world3dExport.frame(seconds), t)
    expectations(shot, document, t, memory)
  }
  const byId = new Map(document.slots.filter(slot => slot.screen?.directional).map(slot => [slot.id, slot.screen!.directional!] as const))
  for (const t of times) {
    const png = await page.evaluate(async seconds => (window as unknown as { __world3dExport: Renderer }).__world3dExport.frame(seconds), t)
    const want = expectations(shot, document, t, memory)
    const probes = want.map(item => probeOf(item, byId.get(item.id)!))
    const measured = await page.evaluate(`${MEASURE}(${JSON.stringify(png)}, ${JSON.stringify(probes)}, 16, ${JSON.stringify({ ...PIP, count: WALK_CELLS })})`) as Measured[]
    if (shot.name === 'overlap') { failures.push(...await overlapFailures(page, png, want, t)); judged += want.length }
    else if (shot.name === 'occlude') { failures.push(...await occlusionFailures(page, png, want, shot, document, t)); judged += 2 }
    else want.forEach((item, index) => {
      const result = judge(t, item, measured[index], want, byId.get(item.id)!)
      failures.push(...result.failures)
      if (result.judged) judged += 1
    })
    frames.push({ t, png, lines: want.map(label) })
    fadeCounts.push(measured[0]?.counts ?? {})
    report.push({ t, figures: want.map((item, index) => ({ id: item.id, sheet: item.sheetId, frame: item.frame, mirror: item.mirror, speaking: item.speaking, fade: item.blend?.mix, drew: measured[index].winner, lit: measured[index].lit, bootRow: measured[index].bootBottom, ground: Math.round(item.ground[1]) })) } as never)
    fs.writeFileSync(path.join(out, `${shot.name}-${t.toFixed(3)}.png`), Buffer.from(png.split(',')[1], 'base64'))
  }
  if (shot.times === 'fade') failures.push(...fadeFailures(report), ...bodyFailures(report as unknown as { figures: { drew: string }[] }[], fadeCounts))
  const sheet = await page.evaluate(`${COMPOSE}(${JSON.stringify(frames)}, ${shot.columns}, { width: 640, height: 360 })`) as string
  const sheetPath = path.join(out, `directional-${shot.name}.sheet.png`)
  fs.writeFileSync(sheetPath, Buffer.from(sheet.split(',')[1], 'base64'))
  await page.evaluate(() => (window as unknown as { __world3dExport: Renderer }).__world3dExport.dispose())
  return { shot: shot.name, sheet: sheetPath, judged, failures, frames: report }
}

async function main() {
  const args = process.argv.slice(2)
  const out = path.resolve(argAfter(args, '--out') ?? fs.mkdtempSync(path.join(os.tmpdir(), 'directional-proof-')))
  fs.mkdirSync(out, { recursive: true })
  const plain = kitFiles()
  const bundle = await bundleRenderer(out)
  const { chromium } = await import('playwright')
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  const problems: string[] = []
  const results = []
  try {
    for (const shot of SHOTS) {
      // A shot that asks for a halo gets its own kit: the same pictures with a faint alpha around every figure.
      const kit = shot.halo ? kitFiles(shot.halo) : plain
      const page = await openPage(browser, kit.files, bundle, problems)
      results.push(await proveShot(page, shot, sceneDocument(shot, kit.sheets), out))
      await page.close()
    }
  } finally {
    await browser.close()
  }
  const failures = [...problems, ...results.flatMap(result => result.failures)]
  const judged = results.reduce((sum, result) => sum + result.judged, 0)
  console.log(JSON.stringify({ judged, failures, sheets: results.map(result => result.sheet), frames: results.map(result => ({ shot: result.shot, frames: result.frames })) }))
  if (failures.length || judged < 30) process.exitCode = 1
}

await main()
