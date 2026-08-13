import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/lib/imageGeneration.ts', import.meta.url),
  'utf8',
)

test('local image assets preserve canonical identity from submit, status, and sidecars', () => {
  assert.match(source, /taskId: submitted\.task_id/)
  assert.match(source, /rootTaskId: submitted\.root_task_id/)
  assert.match(source, /taskId: status\.task_id/)
  assert.match(source, /rootTaskId: status\.root_task_id/)
  assert.match(source, /taskId: metadata\.task_id/)
  assert.match(source, /rootTaskId: metadata\.root_task_id/)
  assert.match(source, /existing\.task_id/)
  assert.match(source, /existing\.root_task_id/)
  assert.match(source, /return localAsset\(name, prompt, selected, identity\)/)
})

test('MiniMax reconnects to its saved job and never resubmits a terminal provider failure', () => {
  const minimaxFlow = source
    .split("if (provider === 'minimax')", 2)[1]
    .split('return runLocalImage', 1)[0]

  assert.match(minimaxFlow, /if \(options\?\.existingJobId\)/)
  assert.match(minimaxFlow, /fetchMiniMaxImageJob\(options\.existingJobId\)/)
  assert.equal(minimaxFlow.match(/startMiniMaxImageJob\(/g)?.length, 1)
  assert.doesNotMatch(minimaxFlow, /for \(let attempt/)
  assert.match(minimaxFlow, /return withTaskIdentity\(job\.result\.asset, identity\)/)
})
