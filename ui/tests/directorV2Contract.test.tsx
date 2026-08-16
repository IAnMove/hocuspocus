import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { directorV2Plan } from '../src/api/client'
import {
  DIRECTOR_SKILLS,
  isDirectorSkill,
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
