import assert from 'node:assert/strict'
import test from 'node:test'

import {
  deriveIsGenerating,
  isGenerationJobActive,
} from '../src/lib/generationJobState.ts'

const job = status => ({ status })

test('only active generation jobs keep the global busy flag enabled', () => {
  for (const status of ['queued', 'waiting_resource', 'running', 'cancelling']) {
    assert.equal(isGenerationJobActive(status), true)
    assert.equal(deriveIsGenerating([job('failed'), job(status)]), true)
  }

  assert.equal(deriveIsGenerating([]), false)
  assert.equal(deriveIsGenerating([
    job('completed'),
    job('failed'),
    job('cancelled'),
  ]), false)
})

test('completing the sole active job leaves terminal history non-generating', () => {
  const jobs = [job('failed'), job('cancelled'), job('running')]
  assert.equal(deriveIsGenerating(jobs), true)

  const remaining = jobs.filter(candidate => candidate.status !== 'running')
  assert.deepEqual(remaining.map(candidate => candidate.status), ['failed', 'cancelled'])
  assert.equal(deriveIsGenerating(remaining), false)
})
