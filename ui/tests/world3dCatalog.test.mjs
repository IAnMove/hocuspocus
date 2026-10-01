import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import test from 'node:test'

test('the shared Video 3D catalog matches the editor library', { timeout: 120_000 }, () => {
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'scripts/export-world3d-catalog.mjs', '--check'], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /^ok \d+\n$/)
})
