import assert from 'node:assert/strict'
import test from 'node:test'
import os from 'node:os'
import path from 'node:path'
import {
  assertOutsideRepo,
  assertSoftwareRenderer,
  categoryLabel,
  parseCaptureArgs,
} from '../scripts/atmosCapturePlan.mjs'

test('capture args accept one template and an export flag', () => {
  const parsed = parseCaptureArgs(['atmos-clearing-wide', '--export', '--port', '4199'], {})
  assert.equal(parsed.help, false)
  assert.deepEqual(parsed.ids, ['atmos-clearing-wide'])
  assert.equal(parsed.exportClip, true)
  assert.equal(parsed.port, 4199)
})

test('draft samples are bounded and optional without changing existing capture defaults', () => {
  assert.deepEqual(parseCaptureArgs(['motion-poster-breakout', '--samples', '0,2.5,8'], {}).samples, [0, 2.5, 8])
  assert.equal(parseCaptureArgs(['motion-poster-breakout'], {}).samples, undefined)
  for (const value of ['-1', '601', 'NaN', '0,,2', '0,1,2,3,4,5,6']) assert.throws(() => parseCaptureArgs(['motion-poster-breakout', '--samples', value], {}))
})

test('capture args reject a missing id, a bad port, and an output inside the repo', () => {
  assert.throws(() => parseCaptureArgs([], {}), /template id/)
  assert.throws(() => parseCaptureArgs(['atmos-clearing-wide', '--port', '0'], {}), /Port/)
  const root = path.join(os.tmpdir(), 'hocus-capture-repo')
  assert.throws(() => assertOutsideRepo(path.join(root, 'ui'), root), /outside the repository/)
  assert.equal(assertOutsideRepo(path.join(os.tmpdir(), 'atmos-out'), root), path.join(os.tmpdir(), 'atmos-out'))
})

test('capture args accept a palette, a time of day and a subject file', () => {
  const parsed = parseCaptureArgs(['atmos-waterfall-wide', '--palette', 'amber', '--time', 'morning', '--subject', 'hero.glb'], {})
  assert.equal(parsed.palette, 'amber')
  assert.equal(parsed.time, 'morning')
  assert.equal(parsed.subject, 'hero.glb')
  assert.throws(() => parseCaptureArgs(['atmos-waterfall-wide', '--palette'], {}), /--palette needs a value/)
})

test('capture refuses a hardware renderer and names the Cinema library button', () => {
  assert.throws(() => assertSoftwareRenderer('ANGLE (NVIDIA, NVIDIA GeForce RTX 4090'), /hardware/)
  assert.match(assertSoftwareRenderer('ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)'), /SwiftShader/)
  assert.equal(categoryLabel('cinema'), 'Cinema')
  assert.equal(categoryLabel('action'), 'Action')
})
