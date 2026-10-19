import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect, test } from '@playwright/test'
// @ts-expect-error The audit is a plain ESM script: the CLI and these specs share its functions.
import { WEBGL_ARGS, auditPage, bundleAudit } from '../../scripts/fx-footprint-audit.mjs'

type Frame = { png: string; coverage: number; box: { left: number; top: number; right: number; bottom: number } | null }
const FIXTURE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'tests', 'fixtures', 'series_fx_presence_shot.json')
const fixture = JSON.parse(fs.readFileSync(FIXTURE, 'utf8')) as {
  width: number; height: number; duration: number; frames: number[]; cue: Record<string, unknown>
}

// A halo a Series script wrote with no duration and no size, as the planner compiles it (tests/test_series_shot_extras.py
// checks the cue against the planner), painted by the real painter on the CPU at the start, the middle and the end of a
// 6 s shot of 1920 x 1080: still there, and wide. The old default (1 s, 65 %) is gone by the second frame.
for (const webgl of [true, false]) {
  // eslint-disable-next-line no-empty-pattern -- Playwright reads the fixtures a test uses from this pattern: none.
  test(`a full-shot halo is on screen and wide from the start to the end of the shot (${webgl ? 'WebGL' : 'canvas 2D'})`, async ({}, testInfo) => {
    test.setTimeout(180_000)
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'fx-presence-'))
    const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS })
    try {
      const page = await auditPage(browser, await bundleAudit(work), { webgl })
      const glUp = await page.evaluate(() => Boolean(document.createElement('canvas').getContext('webgl2') ?? document.createElement('canvas').getContext('webgl')))
      expect(glUp, webgl ? 'WebGL did not come up' : 'WebGL was not hidden').toBe(webgl)
      const paint = (cue: unknown, seconds: number): Promise<Frame> =>
        page.evaluate(([value, at, width, height]) => window.fxAudit.frame([value], at, width, height), [cue, seconds, fixture.width, fixture.height] as const)
      expect(fixture.cue.end).toBeGreaterThan(fixture.duration - 0.05)
      for (const [index, seconds] of fixture.frames.entries()) {
        const frame = await paint(fixture.cue, seconds)
        const name = `halo-${webgl ? 'webgl' : 'canvas2d'}-${index}-${seconds}s.png`
        fs.writeFileSync(testInfo.outputPath(name), Buffer.from(frame.png.split(',')[1], 'base64'))
        await testInfo.attach(name, { path: testInfo.outputPath(name), contentType: 'image/png' })
        expect(frame.box, `the halo is painted at ${seconds} s`).not.toBeNull()
        expect(frame.coverage, `it changes a good share of the frame at ${seconds} s`).toBeGreaterThan(0.1)
        expect(frame.box!.bottom - frame.box!.top + 1, 'it spans the frame top to bottom').toBeGreaterThanOrEqual(fixture.height * 0.8)
        expect(frame.box!.right - frame.box!.left + 1, 'and a third of its width at least').toBeGreaterThanOrEqual(fixture.width * 0.3)
      }
      const before = { ...fixture.cue, end: 1, size: 65 }
      expect((await paint(before, fixture.frames[1])).box, 'the old default is over by the middle of the shot').toBeNull()
    } finally {
      await browser.close()
    }
  })
}
