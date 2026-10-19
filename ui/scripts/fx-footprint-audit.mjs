// Footprint audit of the screen effects: every catalog effect painted alone with the real painter, in Chromium on the
// CPU, with and without WebGL (the filmed 3D sprites and the 2D painters they fall back to), and measured for a cut
// against its own box (scripts/fxFootprint.ts).
//
//   node scripts/fx-footprint-audit.mjs                # table; exit 1 when an effect is cut
//   node scripts/fx-footprint-audit.mjs --quick        # one size, one seed
//   node scripts/fx-footprint-audit.mjs --json out.json
//   node scripts/fx-footprint-audit.mjs --sheet dir    # PNG contact sheets, one per mode and instant
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const WEBGL_ARGS = ['--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
const NO_WEBGL = `(() => {
  const original = HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) { return /webgl/.test(String(type)) ? null : original.call(this, type, ...rest) }
})()`

/** The audit page's script: the real painters and the measure in one bundle (no server, no build). */
export async function bundleAudit(dir) {
  const { build } = await import('esbuild')
  const outfile = path.join(dir, 'fx-footprint.js')
  await build({ entryPoints: [path.join(uiRoot, 'scripts', 'fxFootprintEntry.ts')], bundle: true, format: 'iife', platform: 'browser',
    target: 'es2022', outfile, logLevel: 'error', absWorkingDir: uiRoot })
  return fs.readFileSync(outfile, 'utf8')
}

export const SIZES = [30, 50]
export const INSTANTS = [0.08, 0.22, 0.38, 0.52, 0.7, 0.9]
export const SEEDS = [4, 9]

export function samples(kinds, quick = false) {
  return kinds.flatMap(kind => (quick ? [50] : SIZES).map(size => ({ kind, size, instants: INSTANTS, seeds: quick ? [4] : SEEDS })))
}

/** Open a page of the audit bundle; `webgl: false` hides WebGL so the 2D fallbacks are the ones measured. */
export async function auditPage(browser, script, { webgl }) {
  const page = await browser.newPage()
  page.on('pageerror', error => { throw error })
  await page.setContent('<!doctype html><html><body></body></html>')
  if (!webgl) await page.evaluate(NO_WEBGL)
  await page.addScriptTag({ content: script })
  return page
}

/** PNG contact sheets, one per mode and instant, into `dir`. */
export async function writeSheets(dir, { size = 50, only } = {}) {
  const { chromium } = await import('playwright')
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-footprint-'))
  const script = await bundleAudit(work)
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  fs.mkdirSync(dir, { recursive: true })
  try {
    for (const webgl of [true, false]) {
      const page = await auditPage(browser, script, { webgl })
      for (const at of INSTANTS) {
        const url = await page.evaluate(([a, b, c]) => window.fxAudit.sheet(a, b, 4, c), [size, at, only])
        fs.writeFileSync(path.join(dir, `${webgl ? 'webgl' : 'canvas2d'}-${Math.round(at * 100)}.png`), Buffer.from(url.split(',')[1], 'base64'))
      }
      await page.close()
    }
  } finally {
    await browser.close()
  }
}

export async function runAudit({ quick = false, only } = {}) {
  const { chromium } = await import('playwright')
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-footprint-'))
  const script = await bundleAudit(dir)
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  const rows = []
  try {
    for (const webgl of [true, false]) {
      const probe = await auditPage(browser, script, { webgl })
      const kinds = (await probe.evaluate(() => window.fxAudit.kinds)).filter(kind => !only || only.includes(kind))
      await probe.close()
      // A page of its own per effect: the filmed sprites share one WebGL scene, and an effect painted after another
      // in it can come out blank, which would read as "no cut".
      for (const kind of kinds) {
        const page = await auditPage(browser, script, { webgl })
        for (const sample of samples([kind], quick)) rows.push({ mode: webgl ? 'webgl' : 'canvas2d', ...await page.evaluate(item => window.fxAudit.run(item), sample) })
        await page.close()
      }
    }
  } finally {
    await browser.close()
  }
  return rows
}

/** One entry per effect and mode: the worst of its sizes. */
export function summarize(rows) {
  const groups = new Map()
  for (const row of rows) {
    const key = `${row.kind}\t${row.mode}`
    const group = groups.get(key) ?? { kind: row.kind, mode: row.mode, screen: true, cut: false, run: 0, fill: 0, painted: 0, webgl: row.webgl }
    group.cut ||= row.cut
    group.painted += row.painted
    group.run = Math.max(group.run, row.run); group.fill = Math.max(group.fill, row.fill)
    group.screen &&= row.screen
    groups.set(key, group)
  }
  return [...groups.values()]
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2)
  const sheetAt = args.indexOf('--sheet')
  if (sheetAt >= 0) {
    const onlyAt = args.indexOf('--only')
    await writeSheets(args[sheetAt + 1], { only: onlyAt >= 0 ? args[onlyAt + 1].split(',') : undefined })
    process.exit(0)
  }
  const rows = await runAudit({ quick: args.includes('--quick') })
  const table = summarize(rows)
  const jsonAt = args.indexOf('--json')
  if (jsonAt >= 0) fs.writeFileSync(args[jsonAt + 1], JSON.stringify({ rows, table }, null, 1))
  const kinds = [...new Set(table.map(row => row.kind))]
  console.log('effect'.padEnd(18), 'webgl: run fill'.padEnd(26), 'canvas2d: run fill')
  for (const kind of kinds) {
    const cell = mode => {
      const row = table.find(item => item.kind === kind && item.mode === mode)
      return !row.painted ? 'BLANK'.padEnd(26) : row.screen ? 'screen'.padEnd(26) : `${row.run.toFixed(2).padStart(5)} ${row.fill.toFixed(2).padStart(5)} ${row.cut ? 'CUT' : 'ok'}`.padEnd(26)
    }
    console.log(kind.padEnd(18), cell('webgl'), cell('canvas2d'))
  }
  const cut = table.filter(row => row.cut), blank = table.filter(row => !row.painted)
  console.log(`\n${cut.length} effect/mode pairs cut: ${cut.map(row => `${row.kind}(${row.mode})`).join(', ') || 'none'}`)
  console.log(`${blank.length} painted nothing: ${blank.map(row => `${row.kind}(${row.mode})`).join(', ') || 'none'}`)
  process.exitCode = cut.length || blank.length ? 1 : 0
}
