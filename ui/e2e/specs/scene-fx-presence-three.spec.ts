import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect, test, type Page } from '@playwright/test'
// @ts-expect-error The audit and the sheets are plain ESM scripts: the CLI and these specs share their functions.
import { WEBGL_ARGS, auditPage, bundleAudit, runAudit, summarize } from '../../scripts/fx-footprint-audit.mjs'
// @ts-expect-error See above.
import { SHEET_CUES, bundleSheets, sheetCue, sheetPage } from '../../scripts/fx-presence-sheets.mjs'

// The presence effects drawn with Three.js (ui/src/features/sceneFx/presence): painted in this Chromium on the CPU
// (SwiftShader), with and without WebGL. Each has to paint, to end in the air and not at its box, to give the same pixels
// for the same frame (a Series render paints frame by frame), to fall back to the 2D painter without WebGL, and to stay
// fast enough for a render.
const FIXTURE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'tests', 'fixtures', 'series_fx_presence_shot.json')
const shot = JSON.parse(fs.readFileSync(FIXTURE, 'utf8')) as { width: number; height: number; duration: number; frames: number[]; cue: Record<string, unknown> }
type Frame = { png: string; coverage: number; box: { left: number; top: number; right: number; bottom: number } | null }

function watch(page: Page) {
  const problems: string[] = []
  page.on('console', message => { if (message.type() === 'error' || /THREE\.|shader|GLSL/i.test(message.text())) problems.push(message.text().slice(0, 600)) })
  return problems
}
const hashFrame = (page: Page, cue: unknown, seconds: number) => page.evaluate(([c, at]) => window.fxSheet.pixels([c], at, 640, 360), [cue, seconds] as const)

test('every Three.js presence effect paints, never ends in a box and paints the same frame twice (WebGL and 2D fallback)', async () => {
  test.setTimeout(600_000)
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-presence-three-'))
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  try {
    const sheets = await bundleSheets(work)
    const probe = await sheetPage(browser, sheets, { webgl: true })
    const kinds: string[] = await probe.evaluate(() => window.fxSheet.kinds)
    expect(kinds.length, 'ten effects at least').toBeGreaterThanOrEqual(10)
    expect(kinds.filter(kind => !(kind in SHEET_CUES)), 'every effect has a sheet cue').toEqual([])
    expect(await probe.evaluate(() => window.fxSheet.hasWebgl()), 'WebGL came up').toBe(true)
    await probe.close()

    // The footprint audit of #1160 on these effects alone, every size and seed it knows, in both modes.
    const rows = await runAudit({ quick: false, only: kinds })
    expect(rows.filter((row: { mode: string; webgl: boolean }) => row.mode === 'webgl' && !row.webgl).length, 'WebGL did not come up in the WebGL pass').toBe(0)
    const table: Array<{ kind: string; mode: string; cut: boolean; painted: number }> = summarize(rows)
    expect(table.length).toBe(kinds.length * 2)
    expect(table.filter(row => row.cut).map(row => `${row.kind} (${row.mode})`), 'effects cut against their box').toEqual([])
    expect(table.filter(row => !row.painted).map(row => `${row.kind} (${row.mode})`), 'effects that painted nothing').toEqual([])

    // Same frame, same pixels: twice in a page, after other effects were painted in between, and in a page of its own.
    const first = await sheetPage(browser, sheets, { webgl: true })
    const problems = watch(first)
    const again = await sheetPage(browser, sheets, { webgl: true })
    for (const kind of kinds) {
      const cue = sheetCue(kind)
      const a = await hashFrame(first, cue, 1.7)
      expect(await hashFrame(first, cue, 1.7), `${kind}: the same frame twice`).toEqual(a)
      await hashFrame(first, sheetCue(kinds[(kinds.indexOf(kind) + 1) % kinds.length], {}, 3), 4.2)
      expect(await hashFrame(first, cue, 1.7), `${kind}: after another effect was painted`).toEqual(a)
      expect(await hashFrame(again, cue, 1.7), `${kind}: in a fresh page`).toEqual(a)
      expect((await hashFrame(first, cue, 2.9)).hash, `${kind}: the effect moves`).not.toBe(a.hash)
      expect((await hashFrame(first, sheetCue(kind, { seed: 31 }), 1.7)).hash, `${kind}: the seed changes it`).not.toBe(a.hash)
    }
    expect(problems, 'shader or WebGL errors').toEqual([])
    await first.close(); await again.close()

    // Without WebGL each effect is the 2D painter it always was: it paints, and it is not the Three.js picture.
    const flat = await sheetPage(browser, sheets, { webgl: false })
    expect(await flat.evaluate(() => window.fxSheet.hasWebgl()), 'WebGL was hidden').toBe(false)
    const lit = await sheetPage(browser, sheets, { webgl: true })
    for (const kind of kinds) {
      const cue = sheetCue(kind)
      const twoD = await hashFrame(flat, cue, 1.7), three = await hashFrame(lit, cue, 1.7)
      expect(twoD.lit, `${kind}: painted without WebGL`).toBeGreaterThan(0)
      expect(twoD.hash, `${kind}: the 2D painter is not the Three.js one`).not.toBe(three.hash)
    }
    await flat.close(); await lit.close()
  } finally {
    await browser.close()
  }
})

// A halo and a shield as a Series script writes them (no duration, a size by the framing), at the start, the middle and the
// end of a 6 s shot of 1920 x 1080, as a render paints them: each on its own, then together. The shield swells in over its
// first second and fades over its last half second (the 2D shield's own timing): its frames are inside that.
for (const webgl of [true, false]) {
  // eslint-disable-next-line no-empty-pattern -- Playwright reads the fixtures a test uses from this pattern: none.
  test(`a halo and a shield fill a full frame from the start to the end of the shot (${webgl ? 'WebGL' : 'canvas 2D'})`, async ({}, testInfo) => {
    test.setTimeout(180_000)
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-presence-three-'))
    const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
    try {
      const page = await auditPage(browser, await bundleAudit(work), { webgl })
      const paint = (cues: unknown[], seconds: number): Promise<Frame> =>
        page.evaluate(([value, at, width, height]) => window.fxAudit.frame(value, at, width, height), [cues, seconds, shot.width, shot.height] as const)
      const halo = shot.cue
      const shield = { id: 'fx-1', kind: 'shield', start: 0, end: shot.duration - 0.01, x: 50, y: 50, size: 80 }
      const shieldFrames = [1.0, 3.0, 5.2]
      const cases = { halo: [[halo], shot.frames], shield: [[shield], shieldFrames], both: [[halo, shield], shot.frames] } as const
      for (const [name, [cues, frames]] of Object.entries(cases)) for (const [index, seconds] of frames.entries()) {
        const frame = await paint([...cues], seconds)
        const file = `${name}-${webgl ? 'webgl' : 'canvas2d'}-${index}-${seconds}s.png`
        fs.writeFileSync(testInfo.outputPath(file), Buffer.from(frame.png.split(',')[1], 'base64'))
        await testInfo.attach(file, { path: testInfo.outputPath(file), contentType: 'image/png' })
        expect(frame.box, `${name} is painted at ${seconds} s`).not.toBeNull()
        expect(frame.coverage, `${name} changes a share of the frame at ${seconds} s`).toBeGreaterThan(name === 'shield' ? 0.01 : 0.1)
        if (name !== 'shield') expect(frame.box!.bottom - frame.box!.top + 1, 'the halo spans the frame top to bottom').toBeGreaterThanOrEqual(shot.height * 0.8)
      }
      if (webgl) {
        // The halo is the Three.js one, not the 2D painter's picture.
        const flat = await auditPage(browser, await bundleAudit(work), { webgl: false })
        const flatFrame: Frame = await flat.evaluate(([value, at, width, height]) => window.fxAudit.frame(value, at, width, height), [[halo], 3, shot.width, shot.height] as const)
        expect(flatFrame.png).not.toBe((await paint([halo], 3)).png)
      }
    } finally {
      await browser.close()
    }
  })
}

test('two presence effects at once paint a 1280 x 720 frame in well under a second on the CPU', async () => {
  test.setTimeout(300_000)
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-presence-three-'))
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
  try {
    const page = await sheetPage(browser, await bundleSheets(work), { webgl: true })
    const pairs = [['anime_aura', 'shield'], ['smoke', 'fog'], ['stars', 'dust'], ['aurora', 'bubbles'], ['embers', 'meteor_shower']]
    for (const pair of pairs) {
      const cues = pair.map((kind, index) => sheetCue(kind, {}, index))
      const result: { warm: number; perFrame: number } = await page.evaluate(([c]) => window.fxSheet.time(c, 1280, 720, 6, 6), [cues] as const)
      test.info().annotations.push({ type: pair.join(' + '), description: `${result.perFrame.toFixed(0)} ms/frame (first frame ${result.warm.toFixed(0)} ms)` })
      expect(result.perFrame, `${pair.join(' + ')} ms per frame`).toBeLessThan(400)
    }
  } finally {
    await browser.close()
  }
})
