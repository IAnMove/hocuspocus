import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { directorV2Plan } from '../src/api/client'
import {
  DIRECTOR_SKILLS,
  isDirectorSkill,
  isDirectorV2PlanFailureDetail,
  isDirectorV2PlanResponse,
  type DirectorV2PlanResponse,
} from '../src/types'

test('Director v2 API parameters use the shared DirectorSkill contract', () => {
  const request: Parameters<typeof directorV2Plan>[0] = {
    skill_type: 'music_video',
    workspace: 'default',
    plan_job_id: 'director-plan-resume',
  }

  assert.deepEqual(DIRECTOR_SKILLS, ['music_video', 'short_film', 'podcast', 'viral_video', 'comic', 'comic_movie'])
  assert.equal(isDirectorSkill(request.skill_type), true)
  assert.equal(request.plan_job_id, 'director-plan-resume')
  assert.equal(isDirectorSkill('comic_movie'), true)
  assert.equal(isDirectorSkill('not-a-director-skill'), false)
})

test('Director v2 partial failures require an explicit non-rendering resume contract', () => {
  const detail = {
    code: 'director_plan_incomplete',
    message: 'Final batch failed',
    job: {
      jobId: 'director-plan-partial', workspace: 'default', skillType: 'music_video',
      status: 'failed', phase: 'failed', message: 'Recoverable', total: 10,
      completedIndices: [1, 2, 3, 4, 5, 6, 7, 8], missingIndices: [9, 10],
      completedBatches: [{ indices: [1, 2, 3, 4, 5, 6, 7, 8], completedAt: 1 }],
      activeBatch: [], calls: 2, usage: { total_tokens: 900 }, error: 'Final batch failed',
      result: null, createdAt: 1, updatedAt: 2, finishedAt: 2,
    },
    resume: {
      action: 'resume_missing', method: 'POST',
      path: '/api/v1/director/v2/plan/jobs/director-plan-partial/resume?workspace=default',
    },
    imagesQueued: false,
  }

  assert.equal(isDirectorV2PlanFailureDetail(detail), true)
  assert.equal(isDirectorV2PlanFailureDetail({ ...detail, imagesQueued: true }), false)
  assert.equal(isDirectorV2PlanFailureDetail({ ...detail, job: { ...detail.job, missingIndices: ['9'] } }), false)
})

test('Director v2 response guard rejects drifted skill types and malformed prompts', () => {
  const validResponse: DirectorV2PlanResponse = {
    clip_plans: [{ image_prompt: 'A clean keyframe', video_prompt: 'A slow camera move' }],
    production_plan: { skill_type: 'music_video', shots: [] },
    skill_type: 'music_video',
    plan_job_id: 'director-plan-completed',
  }

  assert.equal(isDirectorV2PlanResponse(validResponse), true)
  assert.equal(isDirectorV2PlanResponse({ ...validResponse, plan_job_id: 42 }), false)
  assert.equal(isDirectorV2PlanResponse({
    ...validResponse,
    skill_type: 'legacy_pipeline',
  }), false)
  assert.equal(isDirectorV2PlanResponse({
    ...validResponse,
    clip_plans: [{ image_prompt: 'missing video prompt' }],
  }), false)
  assert.equal(isDirectorV2PlanResponse({
    ...validResponse,
    production_plan: { skill_type: 'legacy_pipeline', shots: [] },
  }), false)
})
