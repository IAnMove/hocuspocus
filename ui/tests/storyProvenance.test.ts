import assert from 'node:assert/strict'
import test from 'node:test'

import { storyDirectorSubmissionProvenance } from '../src/features/stories/provenance.ts'

test('Story music-video handoff keeps exact IDs in the Director submission', () => {
  assert.deepEqual(storyDirectorSubmissionProvenance({
    projectId: 'story-1',
    productionId: 'production-1',
    cueId: 'cue-1',
    candidateId: 'candidate-2',
  }), {
    actor: 'wizard',
    capability: 'start_director_production',
    project_id: 'story-1',
    production_id: 'production-1',
    cue_id: 'cue-1',
    candidate_id: 'candidate-2',
  })
})

test('Director submissions without a Story handoff do not invent provenance', () => {
  assert.equal(storyDirectorSubmissionProvenance(null), undefined)
})
