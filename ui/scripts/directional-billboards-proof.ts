// A real Chromium render, on the CPU, of 3D shots with directional 2D figures.
//
//   npx tsx --tsconfig tsconfig.app.json scripts/directional-billboards-proof.ts --out DIR
//
// It bundles the owned World3D renderer (the one the server exports with), serves a synthetic five-direction kit from memory and
// renders two shots: an 8 s camera orbit around three figures (a still one, one that walks across and one that speaks), and a
// close fixed shot of a figure that walks and stops to speak. It checks the pixels against what `directionalView` chose: the
// colour of the sheet of each figure, the side its nose is on (the mirror), the cell its pips light (the walk cycle), where it
// stands, and the row of its boots against the ground point under it. It writes one contact sheet per shot to
// `DIR/directional-<shot>.sheet.png` and prints one JSON line. A failed check exits 1.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from '../src/features/scene3d/camera.ts'
import { DirectionMemory, directionalView, type DirectionalSprite, type Direction } from '../src/features/scene3d/directionalSprite.ts'
import { referenceEye, walkedSlot } from '../src/features/scene3d/directionalPaint.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from '../src/features/scene3d/types.ts'
import { BOOT, CELL, DIRECTION_COLORS, DIRECTION_ORDER, FIGURE, FEET, IDLE_CELLS, NOSE, PIP, PIP_OFF, PIP_ON, POSE_TORSO, WALK_CELLS, floorPng, posePng, sheetPng, torsoColor } from './directionalProofKit.ts'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const WIDTH = 960, HEIGHT = 540
const WORKSPACE = 'proof'
const WEBGL_ARGS = ['--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
/** Torso top to boots over the figure height, in the synthetic cells (drawCell). */
const TORSO_SHARE = (CELL.height * FEET - 120) / (CELL.height * FIGURE)

type Figure = { id: string; slot: string; heightM: number; at: readonly [number, number]; sprite: Partial<DirectionalSprite>; label: string }
type Shot = { name: string; duration: number; camera: Scene3DDocument['camera']; figures: Figure[]; times: number[]; columns: number }

const SHOTS: Shot[] = [
  { name: 'orbit', duration: 8, columns: 3, times: [0, 1, 2, 3, 4, 5, 6, 7, 8],
    camera: { family: 'orbit', eye: [0, 1.6, 4.2], look: [0, 1, 0], fov: 40, orbitRadius: 7, orbitHeight: 2, orbitTurns: 0.5 },
    figures: [
      { id: 'ana', slot: 'subject_1', heightM: 1.7, at: [0, 0], sprite: { heading: 0 }, label: 'A still, toward' },
      { id: 'luis', slot: 'prop', heightM: 1.8, at: [-4.5, -2], sprite: { walk: { to: [4.5, -2], speed: 1.2, start: 0.25 } }, label: 'B walks +x' },
      { id: 'eva', slot: 'prop', heightM: 1.5, at: [2.4, 1.2], sprite: { heading: 180, speech: [[4.2, 5.6]] }, label: 'C still, away, speaks' },
    ] },
  { name: 'walk', duration: 6, columns: 4, times: [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 2.5],
    camera: { family: 'fixed', eye: [0, 1.3, 6.5], look: [0, 1, 0], fov: 40 },
    figures: [{ id: 'ana', slot: 'subject_1', heightM: 1.8, at: [-3, 0], sprite: { walk: { to: [3, 0], speed: 1.2, start: 0 }, speech: [[2, 3]] }, label: 'walks, speaks 2-3 s' }] },
]

const url = (name: string) => `/api/v1/file/${name}?workspace=${WORKSPACE}`

/** Every file the page asks for, by name, and the sheets as the server hands them to a scene. */
function kitFiles() {
  const files = new Map<string, Buffer>([['pose.png', posePng()], ['floor.png', floorPng()]])
  const sheets: DirectionalSprite['sheets'] = []
  for (const motion of ['walk', 'idle'] as const) for (const dir of DIRECTION_ORDER) {
    const count = motion === 'walk' ? WALK_CELLS : IDLE_CELLS
    const made = sheetPng(dir, motion, count)
    const name = `${motion}-${dir}.png`
    files.set(name, made.png)
    sheets.push({ id: motion === 'walk' ? (dir === 'side' ? 'walk-12' : `walk-${dir}`) : `idle-${dir}`, motion, dir, source: url(name), columns: made.columns, rows: made.rows, count,
      cell: { ...CELL }, fps: motion === 'walk' ? 8 : 2, loop: motion === 'walk' ? 'loop' : 'pingpong' })
  }
  return { files, sheets }
}

function sceneDocument(shot: Shot, sheets: DirectionalSprite['sheets']): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  // The legacy look: no tone mapping, so a flat colour comes out as itself.
  delete document.look
  delete document.lighting
  document.width = WIDTH; document.height = HEIGHT; document.duration = shot.duration; document.camera = shot.camera
  const floor: Scene3DSlot = { id: 'floor', slot: 'background', position: [0, 0.004, 0], rotationY: 0, scale: 8, sourceUrl: url('floor.png'), media: 'image', surface: 'floor', textureRepeat: 1, clip: null }
  const figures = shot.figures.map(figure => ({
    id: figure.id, slot: figure.slot as Scene3DSlot['slot'], position: [figure.at[0], 0, figure.at[1]] as Vec3, rotationY: 0, scale: figure.heightM / 2,
    sourceUrl: url('pose.png'), media: 'image' as const, surface: 'cutout' as const, grounded: true, billboard: true, clip: null,
    imageLook: { unlit: true, grounded: true, shadow: 0.5 },
    screen: { media: 'image', sourceUrl: url('pose.png'), directional: { sheets, ...figure.sprite } },
  } as unknown as Scene3DSlot))
  document.slots = [floor, ...figures]
  return document
}

type Rect = [number, number, number, number]
type Expectation = { id: string; dir: Direction; motion: string; mirror: boolean; frame: number | null; rect: Rect; ground: [number, number]; headY: number; sheet: string }

/** What the chooser picked for each figure at `t`, and where the figure is on the screen: the oracle of the pixels. */
function expectations(shot: Shot, document: Scene3DDocument, t: number, memory: DirectionMemory): Expectation[] {
  const posed = document.slots.map(slot => walkedSlot({ ...slot }, slot.position, t))
  const eye = cameraEyeAtTime(document.camera, t, document.duration, posed), look = cameraLookAtTime(document.camera, t, document.duration, posed)
  const eye0 = referenceEye(document)
  return posed.flatMap((slot, index) => {
    const sprite = slot.screen?.directional
    if (!sprite) return []
    const { view } = directionalView(sprite, { start: [document.slots[index].position[0], document.slots[index].position[2]], eye0, eye: [eye[0], eye[2]], t, memory, id: slot.id })
    const height = shot.figures.find(figure => figure.id === slot.id)!.heightM
    const feet = projectPoint(slot.position, eye, look, document.camera.fov, WIDTH / HEIGHT)!
    const head = projectPoint([slot.position[0], slot.position[1] + height, slot.position[2]], eye, look, document.camera.fov, WIDTH / HEIGHT)!
    const high = head.y * HEIGHT, low = feet.y * HEIGHT, span = low - high, half = span * 0.45
    const picked = view.kind === 'sheet' ? sprite.sheets[view.sheet] : null
    return [{ id: slot.id, dir: picked?.dir ?? 'front', motion: picked?.motion ?? 'pose', mirror: view.kind === 'sheet' && view.mirror, frame: view.kind === 'sheet' ? view.frame : null,
      rect: [Math.round(feet.x * WIDTH - half), Math.round(high - span * 0.3), Math.round(feet.x * WIDTH + half), Math.round(low + span * 0.06)] as Rect,
      ground: [feet.x * WIDTH, low] as [number, number], headY: high, sheet: picked?.id ?? 'pose' }]
  })
}

/** Runs in the page: the pixels of one frame measured against the rectangle of each figure. */
const MEASURE = `(async (dataUrl, rects, palette, colors, tolerance, pip) => {
  const image = new Image(); image.src = dataUrl; await image.decode()
  const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
  const context = canvas.getContext('2d', { willReadFrequently: true }); context.drawImage(image, 0, 0)
  const near = (r, g, b, c, limit = tolerance) => Math.abs(r - c[0]) <= limit && Math.abs(g - c[1]) <= limit && Math.abs(b - c[2]) <= limit
  return rects.map(rect => {
    const [x0, y0, x1, y1] = rect
    const left = Math.max(0, x0), top = Math.max(0, y0), width = Math.min(canvas.width, x1) - left, height = Math.min(canvas.height, y1) - top
    const data = context.getImageData(left, top, width, height).data
    const counts = {}, rows = {}; let noseX = 0, noseN = 0, bodyX = 0, bodyN = 0, bootRow = -1, onX = 0, onN = 0, minX = 1e9, maxX = -1
    for (let y = 0; y < height; y += 1) {
      let boots = 0
      for (let x = 0; x < width; x += 1) {
        const i = (y * width + x) * 4, r = data[i], g = data[i + 1], b = data[i + 2]
        if (near(r, g, b, colors.on, 4)) { onX += x; onN += 1; minX = Math.min(minX, x); maxX = Math.max(maxX, x); continue }
        if (near(r, g, b, colors.off, 4)) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); continue }
        let classed = false
        for (const [name, color] of Object.entries(palette)) if (near(r, g, b, color)) { counts[name] = (counts[name] || 0) + 1; (rows[name] = rows[name] || {})[y] = ((rows[name] || {})[y] || 0) + 1; bodyX += x; bodyN += 1; classed = true; break }
        if (!classed && near(r, g, b, colors.nose)) { noseX += x; noseN += 1 }
        if (near(r, g, b, colors.boot, 8)) boots += 1
      }
      if (boots >= 3) bootRow = y
    }
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || ['none', 0]
    const heavy = Object.entries(rows[best[0]] || {}).filter(([, n]) => n >= 6).map(([y]) => Number(y)).sort((a, b) => a - b)
    const topRow = heavy.length ? heavy[0] : -1
    const extent = (pip.count - 1) * pip.pitch + pip.width, scale = (maxX - minX + 1) / extent
    const lit = onN && maxX > minX ? Math.round((left + onX / onN - (left + minX) - pip.width * scale / 2) / (pip.pitch * scale)) : null
    return { winner: best[0], pixels: best[1], bodyCentre: bodyN ? left + bodyX / bodyN : null, noseCentre: noseN ? left + noseX / noseN : null,
      bootBottom: bootRow >= 0 ? top + bootRow : null, topRow: topRow >= 0 ? top + topRow : null, lit }
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
    context.fillStyle = '#fff'; context.fillText('t = ' + frame.t.toFixed(2) + ' s', x + 6, y + 14)
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
const palette = () => Object.fromEntries([...DIRECTION_ORDER.flatMap(dir => (['walk', 'idle'] as const).map(motion => [`${motion}-${dir}`, torsoColor(dir, motion)] as const)), ['pose', POSE_TORSO] as const])

type Measured = { winner: string; pixels: number; bodyCentre: number | null; noseCentre: number | null; bootBottom: number | null; topRow: number | null; lit: number | null }
type Page = import('playwright').Page
type Renderer = { load: (d: unknown, s: unknown) => Promise<void>; frame: (s: number) => Promise<string>; dispose: () => void }

const overlap = (a: Rect, b: Rect) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]
const inside = (rect: Rect) => rect[0] >= 0 && rect[1] >= 0 && rect[2] <= WIDTH && rect[3] <= HEIGHT
const central = (want: Expectation) => Math.abs(want.ground[0] - WIDTH / 2) < WIDTH * 0.35 && want.ground[1] < HEIGHT - 6

/** The checks of one figure in one frame; a figure that is clipped by the frame or covered by another is not judged. */
function judge(t: number, want: Expectation, got: Measured, others: Expectation[]): { failures: string[]; judged: boolean } {
  const name = `t=${t} ${want.id}`
  if (!inside(want.rect) || others.some(other => other !== want && overlap(want.rect, other.rect))) return { failures: [], judged: false }
  const failures: string[] = []
  const expected = want.motion === 'pose' ? 'pose' : `${want.motion}-${want.dir}`
  if (got.winner !== expected) failures.push(`${name}: drew ${got.winner}, the chooser asked for ${expected}`)
  if (want.motion !== 'pose' && ['side', 'front34'].includes(want.dir) && got.noseCentre !== null && got.bodyCentre !== null && (got.noseCentre > got.bodyCentre) === want.mirror) {
    failures.push(`${name}: the nose is on the ${want.mirror ? 'right' : 'left'} but mirror is ${want.mirror}`)
  }
  if (want.frame !== null && want.motion === 'walk' && !want.mirror && got.lit !== want.frame) failures.push(`${name}: lit cell ${got.lit}, the walk is at cell ${want.frame}`)
  if (!central(want)) return { failures, judged: true }
  if (got.bodyCentre !== null && Math.abs(got.bodyCentre - want.ground[0]) > 10) failures.push(`${name}: stands at x ${got.bodyCentre.toFixed(0)}, should be ${want.ground[0].toFixed(0)}`)
  if (got.bootBottom === null) failures.push(`${name}: no boots found`)
  else if (Math.abs(got.bootBottom - want.ground[1]) > 4) failures.push(`${name}: boots end at row ${got.bootBottom}, the ground under the figure is row ${want.ground[1].toFixed(1)}`)
  if (got.topRow !== null && want.motion !== 'pose') {
    const ratio = (want.ground[1] - got.topRow) / (want.ground[1] - want.headY)
    if (ratio < TORSO_SHARE - 0.07 || ratio > TORSO_SHARE + 0.06) failures.push(`${name}: the torso reaches ${(ratio * 100).toFixed(0)} % of the figure height, not about ${(TORSO_SHARE * 100).toFixed(0)} %`)
  }
  return { failures, judged: true }
}

async function openPage(browser: import('playwright').Browser, files: Map<string, Buffer>, bundle: string, problems: string[]): Promise<Page> {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } })
  page.on('pageerror', error => problems.push(`page error: ${error.message}`))
  page.on('console', message => { if (message.type() === 'error') problems.push(`console error: ${message.text().slice(0, 400)}`) })
  await page.route('http://hp.local/**', async route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop() ?? '')
    const body = files.get(name)
    if (body) await route.fulfill({ status: 200, contentType: 'image/png', body })
    else await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><html><body style="margin:0"><div id="root"></div></body></html>' })
  })
  await page.goto('http://hp.local/')
  await page.addScriptTag({ content: bundle })
  return page
}

async function proveShot(page: Page, shot: Shot, document: Scene3DDocument, out: string) {
  await page.evaluate(async ([doc, size]) => { await (window as unknown as { __world3dExport: Renderer }).__world3dExport.load(doc, size) }, [document, { width: WIDTH, height: HEIGHT, fps: 30 }] as const)
  const frames: { t: number; png: string; lines: string[] }[] = [], failures: string[] = [], report: unknown[] = []
  let judged = 0
  // The renderer holds a figure's sector from frame to frame; the oracle follows the same frames in the same order.
  const memory = new DirectionMemory()
  for (const t of shot.times) {
    const png = await page.evaluate(async seconds => (window as unknown as { __world3dExport: Renderer }).__world3dExport.frame(seconds), t)
    const want = expectations(shot, document, t, memory)
    const colors = { on: PIP_ON, off: PIP_OFF, nose: NOSE, boot: BOOT }
    const measured = await page.evaluate(`${MEASURE}(${JSON.stringify(png)}, ${JSON.stringify(want.map(item => item.rect))}, ${JSON.stringify(palette())}, ${JSON.stringify(colors)}, 16, ${JSON.stringify({ ...PIP, count: WALK_CELLS })})`) as Measured[]
    want.forEach((item, index) => {
      const result = judge(t, item, measured[index], want)
      failures.push(...result.failures)
      if (result.judged) judged += 1
    })
    frames.push({ t, png, lines: want.map(item => `${item.id}: ${item.sheet}${item.frame !== null ? `#${item.frame}` : ''}${item.mirror ? ' mirrored' : ''}`) })
    report.push({ t, figures: want.map((item, index) => ({ id: item.id, sheet: item.sheet, frame: item.frame, mirror: item.mirror, drew: measured[index].winner, lit: measured[index].lit, bootRow: measured[index].bootBottom, ground: Math.round(item.ground[1]) })) })
    fs.writeFileSync(path.join(out, `${shot.name}-${t.toFixed(2)}.png`), Buffer.from(png.split(',')[1], 'base64'))
  }
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
  const { files, sheets } = kitFiles()
  const bundle = await bundleRenderer(out)
  const { chromium } = await import('playwright')
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  const problems: string[] = []
  const results = []
  try {
    for (const shot of SHOTS) {
      const page = await openPage(browser, files, bundle, problems)
      results.push(await proveShot(page, shot, sceneDocument(shot, sheets), out))
      await page.close()
    }
  } finally {
    await browser.close()
  }
  const failures = [...problems, ...results.flatMap(result => result.failures)]
  const judged = results.reduce((sum, result) => sum + result.judged, 0)
  console.log(JSON.stringify({ judged, failures, sheets: results.map(result => result.sheet), frames: results.map(result => ({ shot: result.shot, frames: result.frames })) }))
  if (failures.length || judged < 20) process.exitCode = 1
}

await main()
