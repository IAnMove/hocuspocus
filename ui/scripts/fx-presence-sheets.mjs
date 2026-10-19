// Contact sheets, timing and determinism checks of the presence effects, painted by the real painter in Chromium on the CPU.
//
//   node scripts/fx-presence-sheets.mjs --out DIR [--kinds a,b] [--tag before] [--no-webgl] [--light] [--wide 1280] [--cue '{"size":50}']
//   node scripts/fx-presence-sheets.mjs --out DIR --compare          # before (2D) over after (Three.js), three instants
//   node scripts/fx-presence-sheets.mjs --out DIR --still --at 3    # one full-size frame per effect
//   node scripts/fx-presence-sheets.mjs --time [--kinds a,b] [--wide 1280] [--before]   # ms per frame, each alone and the two together (--before: the 2D painters)
//
// One PNG per effect: its frames at the start, the middle and the end of a 6 s shot over a scene-like backdrop. ``--tag``
// names the file (``before``/``after``); ``--no-webgl`` hides WebGL so the 2D painters are the ones shown.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { WEBGL_ARGS } from './fx-footprint-audit.mjs'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const NO_WEBGL = `(() => {
  const original = HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) { return /webgl/.test(String(type)) ? null : original.call(this, type, ...rest) }
})()`

/** The cue a Series script gets for each presence effect (sizes as `series_fx_classes` compiles them for a subject in a medium shot). */
export const SHEET_CUES = {
  anime_aura: { size: 80, y: 60 }, shield: { size: 80, y: 60 }, smoke: { size: 80 }, fog: {}, dust: { size: 125 }, light_rays: {},
  stars: { size: 125 }, embers: { size: 125 }, energy_orb: { size: 100 }, fire: { size: 80 }, aurora: { size: 125 }, bubbles: { size: 125 },
  black_hole: { size: 80 }, portal: { size: 80 }, magic_circle: { size: 80 }, snow: {}, rain: {}, meteor_shower: { size: 125 },
}
export const INSTANTS = [0.05, 0.5, 0.95]
export const SHOT = 6

export function sheetCue(kind, extra = {}, index = 0) {
  return { id: `fx-${index}`, kind, start: 0, end: SHOT - 0.01, x: 50, y: 50, intensity: 1, seed: 7 + index, ...SHEET_CUES[kind], ...extra }
}

export async function bundleSheets(dir) {
  const { build } = await import('esbuild')
  const outfile = path.join(dir, 'fx-presence-sheet.js')
  await build({ entryPoints: [path.join(uiRoot, 'scripts', 'fxPresenceSheetEntry.ts')], bundle: true, format: 'iife', platform: 'browser',
    target: 'es2022', outfile, logLevel: 'error', absWorkingDir: uiRoot })
  return fs.readFileSync(outfile, 'utf8')
}

export async function sheetPage(browser, script, { webgl }) {
  const page = await browser.newPage()
  page.on('pageerror', error => { throw error })
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) console.log(`[page ${message.type()}] ${message.text().slice(0, 1500)}`) })
  await page.setContent('<!doctype html><html><body></body></html>')
  if (!webgl) await page.evaluate(NO_WEBGL)
  await page.addScriptTag({ content: script })
  return page
}

const argAfter = (args, flag) => { const at = args.indexOf(flag); return at >= 0 ? args[at + 1] : undefined }

async function main() {
  const args = process.argv.slice(2)
  const extra = JSON.parse(argAfter(args, '--cue') ?? '{}')
  const kinds = (argAfter(args, '--kinds') ?? Object.keys(SHEET_CUES).join(',')).split(',')
  const webgl = !args.includes('--no-webgl'), light = args.includes('--light')
  const { chromium } = await import('playwright')
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-presence-'))
  const script = await bundleSheets(work)
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  try {
    const page = await sheetPage(browser, script, { webgl })
    if (args.includes('--time')) {
      if (args.includes('--before')) await page.evaluate(() => window.fxSheet.presence(false))
      const pair = [sheetCue(kinds[0], extra, 0), sheetCue(kinds[1] ?? kinds[0], extra, 1)]
      for (const cues of [[pair[0]], [pair[1]], pair]) {
        const wide = Number(argAfter(args, '--wide') ?? 1280)
        const result = await page.evaluate(([c, w, h]) => window.fxSheet.time(c, w, h, 8, 6), [cues, wide, Math.round(wide * 9 / 16)])
        console.log(cues.map(cue => cue.kind).join(' + '), `warm ${result.warm.toFixed(0)} ms, ${result.perFrame.toFixed(0)} ms/frame`)
      }
      return
    }
    const out = argAfter(args, '--out')
    const tag = argAfter(args, '--tag') ?? 'sheet'
    if (args.includes('--still')) {
      // One full-size frame per effect at `--at` seconds (default 3), as `kind.tag.still.png`.
      fs.mkdirSync(out, { recursive: true })
      for (const kind of kinds) {
        const url = await page.evaluate(([cue, at, w, h, back]) => window.fxSheet.still([cue], at, w, h, back), [sheetCue(kind, extra), Number(argAfter(args, '--at') ?? 3), Number(argAfter(args, '--wide') ?? 1280), Math.round(Number(argAfter(args, '--wide') ?? 1280) * 9 / 16), light ? 'light' : 'scene'])
        fs.writeFileSync(path.join(out, `${kind}.${tag}.still${webgl ? '' : '.2d'}.png`), Buffer.from(url.split(',')[1], 'base64'))
      }
      return
    }
    const width = Number(argAfter(args, '--wide') ?? 1280), height = Math.round(width * 9 / 16)
    fs.mkdirSync(out, { recursive: true })
    for (const kind of kinds) {
      // `--compare`: the 2D painters (before) over the Three.js ones (after), one picture per effect.
      const rows = args.includes('--compare')
        ? [{ label: `${kind} before`, cues: [sheetCue(kind, extra)], presence: false }, { label: `${kind} after`, cues: [sheetCue(kind, extra)], presence: true }]
        : [{ label: kind, cues: [sheetCue(kind, extra)] }]
      const tileWidth = Number(argAfter(args, '--tile') ?? 560)
      const url = await page.evaluate(spec => window.fxSheet.sheet(spec),
        { rows, instants: INSTANTS, duration: SHOT, width, height, tileWidth, backdrop: light ? 'light' : 'scene' })
      fs.writeFileSync(path.join(out, `${kind}.${tag}${webgl ? '' : '.2d'}${light ? '.light' : ''}.png`), Buffer.from(url.split(',')[1], 'base64'))
    }
  } finally {
    await browser.close()
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
