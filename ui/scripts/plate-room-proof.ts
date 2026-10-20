// A real Chromium render, on the CPU, of a plate room (app/services/room_plate.py) through the owned World3D renderer: the one the server
// exports with, so `lensShift`, the unlit GLB, the tone mapping and the depth test of the directional sprites are the app's own.
//
//   npx tsx --tsconfig tsconfig.app.json scripts/plate-room-proof.ts --spec SPEC.json --out DIR
//
// SPEC.json is written by a Python driver (tests/test_room_plate.py, `HOCUSPOCUS_BROWSER_PROOF=1`): `{glb, width, height, size, camera, look,
// frames: [{name, figures: [{id, x, z, heightM}]}]}`. `glb` is a file built by `scene3d.room.put`; `camera` is `plate.camera` of the stored
// room. Each frame is staged the way production stages a box room (`stageRoomBox`), the figures are directional sprites (the kit's front
// idle sheet, so they are depth tested like #1170's), and one PNG per frame goes to `DIR/<name>.png`. The Python side measures the pixels.
// `look` is `default` (what a new scene wears: ACES at -0.5 EV), `none` (no look: the cinematic path still tone maps with ACES), `neutral`
// or `off` (`toneMapping: 'none'`, the picture as drawn).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { stageRoomBox } from '../src/features/scene3d/roomBox.ts'
import type { DirectionalSprite } from '../src/features/scene3d/directionalSprite.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from '../src/features/scene3d/types.ts'
import { CELL, DIRECTION_ORDER, posePng, sheetPng } from './directionalProofKit.ts'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const WORKSPACE = 'proof'
const WEBGL_ARGS = ['--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
const url = (name: string) => `/api/v1/file/${name}?workspace=${WORKSPACE}`

type Figure = { id: string; x: number; z: number; heightM: number }
type Spec = {
  glb: string; width: number; height: number; size: { w: number; d: number; h: number }
  camera: { eye: Vec3; look: Vec3; fov: number; lensShift: number }
  look?: 'default' | 'none' | 'neutral' | 'off'; frames: { name: string; figures: Figure[] }[]
}

/** The idle sheet of each direction, as the server hands them to a scene. */
function kit() {
  const files = new Map<string, Buffer>([['pose.png', posePng()]])
  const sheets: DirectionalSprite['sheets'] = []
  for (const dir of DIRECTION_ORDER) {
    const made = sheetPng(dir, 'idle', 4, false)
    files.set(`idle-${dir}.png`, made.png)
    sheets.push({ id: `idle-${dir}`, motion: 'idle', dir, source: url(`idle-${dir}.png`), columns: made.columns, rows: made.rows, count: 4, cell: { ...CELL }, fps: 2, loop: 'pingpong' })
  }
  return { files, sheets }
}

function stage(spec: Spec, frame: Spec['frames'][number], sheets: DirectionalSprite['sheets']): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  document.width = spec.width; document.height = spec.height; document.duration = 1
  stageRoomBox(document, { size: spec.size, door: null, plate: { camera: spec.camera }, file: url('room.glb') })
  if (spec.look === 'none') delete document.look
  else if (spec.look === 'neutral') document.look = { toneMapping: 'neutral', exposure: 0 }
  else if (spec.look === 'off') document.look = { toneMapping: 'none', exposure: 0 }
  const room = document.slots.find(slot => slot.id === 'room-box')!
  const figures = frame.figures.map(figure => ({
    id: figure.id, slot: 'prop' as const, position: [figure.x, 0, figure.z] as Vec3, rotationY: 0, scale: figure.heightM / 2,
    sourceUrl: url('pose.png'), media: 'image' as const, surface: 'cutout' as const, grounded: true, billboard: true, clip: null,
    imageLook: { grounded: true, shadow: 0.5 },
    screen: { media: 'image', sourceUrl: url('pose.png'), directional: { sheets, heading: 0 } },
  } as unknown as Scene3DSlot))
  document.slots = [room, ...figures]
  return document
}

async function bundleRenderer(dir: string) {
  const { build } = await import('esbuild')
  const outfile = path.join(dir, 'owned-renderer.js')
  await build({ entryPoints: [path.join(uiRoot, 'src/features/scene3d/ownedRenderer.tsx')], bundle: true, format: 'iife', platform: 'browser', target: 'es2022', outfile,
    logLevel: 'error', absWorkingDir: uiRoot, tsconfig: path.join(uiRoot, 'tsconfig.app.json'), loader: { '.css': 'empty' },
    define: { 'import.meta.env': '{"DEV":false,"PROD":true,"MODE":"production","BASE_URL":"/"}', 'process.env.NODE_ENV': '"production"' } })
  return fs.readFileSync(outfile, 'utf8')
}

const argAfter = (args: string[], flag: string) => { const at = args.indexOf(flag); return at >= 0 ? args[at + 1] : undefined }
type Renderer = { load: (d: unknown, s: unknown) => Promise<void>; frame: (s: number) => Promise<string>; dispose: () => void }

async function main() {
  const args = process.argv.slice(2)
  const spec = JSON.parse(fs.readFileSync(path.resolve(argAfter(args, '--spec') ?? ''), 'utf8')) as Spec
  const out = path.resolve(argAfter(args, '--out') ?? '.')
  fs.mkdirSync(out, { recursive: true })
  const { files, sheets } = kit()
  files.set('room.glb', fs.readFileSync(spec.glb))
  const bundle = await bundleRenderer(out)
  const { chromium } = await import('playwright')
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  const problems: string[] = []
  const written: string[] = []
  try {
    for (const frame of spec.frames) {
      const page = await browser.newPage({ viewport: { width: spec.width, height: spec.height } })
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
      await page.evaluate(async ([doc, size]) => { await (window as unknown as { __world3dExport: Renderer }).__world3dExport.load(doc, size) },
        [stage(spec, frame, sheets), { width: spec.width, height: spec.height, fps: 30 }] as const)
      const png = await page.evaluate(async seconds => (window as unknown as { __world3dExport: Renderer }).__world3dExport.frame(seconds), 0.5)
      const file = path.join(out, `${frame.name}.png`)
      fs.writeFileSync(file, Buffer.from(png.split(',')[1], 'base64'))
      written.push(file)
      await page.evaluate(() => (window as unknown as { __world3dExport: Renderer }).__world3dExport.dispose())
      await page.close()
    }
  } finally {
    await browser.close()
  }
  console.log(JSON.stringify({ frames: written, problems }))
  if (problems.length) process.exitCode = 1
}

await main()
