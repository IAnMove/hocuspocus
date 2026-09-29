import assert from 'node:assert/strict'
import test from 'node:test'
import type { MontageShotBoard } from '../src/api/montages.ts'
import { formatSlot, hasPendingTakes, sceneOutput, shortPrompt } from '../src/features/video-editor/shotBoardModel.ts'

const board = (status: string): MontageShotBoard => ({ file: 'a.montage.json', name: 'a', revision: 2, duration: 10, shots: [{
  index: 0, id: 's1', name: 'Shot', start: 0, end: 5, source: 'a.mp4', url: '/a', lyric: '',
  provenance: { kind: 'generation', canRegenerate: true }, takes: [{ id: 't', status }],
}] })

test('slots read as minutes and tenths', () => {
  assert.equal(formatSlot(5.5, 72.04), '0:05.5–1:12.0')
})

test('pending takes keep the board polling until they finish or fail', () => {
  assert.equal(hasPendingTakes(board('queued')), true)
  assert.equal(hasPendingTakes(board('running')), true)
  assert.equal(hasPendingTakes(board('completed')), false)
  assert.equal(hasPendingTakes(board('failed')), false)
})

test('prompts are shortened on one line', () => {
  assert.equal(shortPrompt('a  b\nc'), 'a b c')
  assert.equal(shortPrompt('x'.repeat(200), 10), `${'x'.repeat(9)}…`)
})

test('sceneOutput is the saved scene file the editor opens', () => {
  const file = sceneOutput('my ws', 'song-intro-1a2b.scene.json')
  assert.equal(file.type, 'scene')
  assert.equal(file.name, 'song-intro-1a2b.scene.json')
  assert.equal(file.url, '/api/v1/file/song-intro-1a2b.scene.json?workspace=my%20ws')
})
