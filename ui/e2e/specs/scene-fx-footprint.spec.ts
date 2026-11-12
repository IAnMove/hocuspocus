import { expect, test } from '@playwright/test'
// @ts-expect-error The audit is a plain ESM script: the CLI and this spec share its functions.
import { runAudit, summarize } from '../../scripts/fx-footprint-audit.mjs'

type Sample = { mode: string; webgl: boolean }
type Row = { kind: string; mode: string; cut: boolean; painted: number }

// Every catalog effect painted alone by the real painter in this Chromium, with WebGL (the filmed 3D sprites) and
// without it (the 2D painters they fall back to), and measured for paint that stops flat at its own box
// (scripts/fxFootprint.ts). The same audit runs from the shell: `node scripts/fx-footprint-audit.mjs`.
test('no screen effect ends in a box, and none comes out blank', async () => {
  test.setTimeout(300_000)
  const rows: Sample[] = await runAudit({ quick: true })
  // Without WebGL the "webgl" pass would measure the 2D fallbacks twice and the filmed 3D sprites never.
  expect(rows.filter(row => row.mode === 'webgl' && !row.webgl).length, 'WebGL did not come up in the WebGL pass').toBe(0)
  const table: Row[] = summarize(rows)
  expect(table.length).toBeGreaterThan(100)
  expect(table.filter(row => row.cut).map(row => `${row.kind} (${row.mode})`), 'effects cut against their box').toEqual([])
  expect(table.filter(row => !row.painted).map(row => `${row.kind} (${row.mode})`), 'effects that painted nothing').toEqual([])
})
