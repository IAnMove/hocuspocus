import assert from 'node:assert/strict'
import test from 'node:test'
import type { RigCapabilities, RigProfile } from '../src/api/model3d'
import {
  clampBpm, clipGroups, clipIsRecommended, clipsForEngine, humanoidClipSelection, previewAsset, recommendedClipIds,
  isRigSource, refusalKey, rigFooterKey, rigHelpKey, rigJobBody, rigLabel, warningKeys,
} from '../src/components/Sidebar/humanoidRig'

const profile = {
  id: 'humanoid',
  label: 'Humanoid',
  description: '',
  default_spine_joints: 5,
  default_axis_mode: 'y',
  default_weight_falloff: 2,
  recommended_animations: ['idle', 'walk'],
  allowed_animations: ['idle', 'walk', 'spin'],
} satisfies RigProfile

const capabilities = {
  engines: [],
  animations: [
    { id: 'idle', label: 'Idle', description: '' },
    { id: 'walk', label: 'Walk', description: '' },
    { id: 'spin', label: 'Spin', description: '' },
  ],
  humanoid_animations: [
    { id: 'idle', label: 'Idle', description: '', category: 'Stand' },
    { id: 'walk', label: 'Walk', description: '', category: 'Move' },
    { id: 'wave', label: 'Wave', description: '', category: 'Gesture' },
    { id: 'talk', label: 'Talk', description: '', category: 'Gesture' },
    { id: 'dance_side', label: 'Dance Side', description: '', category: 'Dance' },
  ],
  default_spine_joints: 5,
  active_jobs: 0,
} satisfies RigCapabilities

test('humanoid engine lists its own clips, grouped, with its own previews', () => {
  assert.deepEqual(clipsForEngine('humanoid', capabilities, profile).map(item => item.id), ['idle', 'walk', 'wave', 'talk', 'dance_side'])
  assert.deepEqual(clipsForEngine('procedural', capabilities, profile).map(item => item.id), ['idle', 'walk', 'spin'])
  assert.deepEqual(recommendedClipIds('humanoid', capabilities, profile, []), ['idle', 'walk', 'wave', 'talk'])
  assert.equal(clipIsRecommended('humanoid', 'wave', profile, ['wave']), true)
  assert.equal(clipIsRecommended('procedural', 'wave', profile, ['walk']), false)
  assert.deepEqual(clipGroups(capabilities.humanoid_animations).map(group => group.category), ['Move', 'Gesture', 'Dance', 'Stand'])
  assert.equal(previewAsset('humanoid', 'walk'), 'humanoid-walk')
  assert.equal(previewAsset('procedural', 'walk'), 'animation-walk')
  assert.deepEqual(humanoidClipSelection(['idle', 'walk', 'wave', 'talk', 'dance_side']), ['idle', 'walk', 'wave', 'talk'])
  assert.equal(rigHelpKey('humanoid'), 'rig.humanoidHelp')
  assert.equal(rigFooterKey('humanoid'), 'rig.humanoidFooter')
  assert.equal(rigFooterKey('procedural'), 'rig.proceduralFooter')
})

test('humanoid jobs send a tempo and no procedural fit', () => {
  const body = rigJobBody({
    source: 'pet.glb', engineId: 'humanoid', rigProfileId: 'humanoid', clips: ['walk'],
    bpm: 250, spineJoints: 7, axisMode: 'x', weightFalloff: 3,
  })
  assert.equal(body.animation_bpm, 180)
  assert.equal('spine_joints' in body, false)
  assert.equal('pose' in body, false)
  const procedural = rigJobBody({
    source: 'box.glb', engineId: 'procedural', rigProfileId: 'prop', clips: ['spin'],
    bpm: 120, spineJoints: 4, axisMode: 'y', weightFalloff: 2,
  })
  assert.equal(procedural.spine_joints, 4)
  assert.equal('animation_bpm' in procedural, false)
  assert.equal(clampBpm(Number.NaN), 120)
  assert.equal(clampBpm(59.6), 60)
})

test('refusals and warnings map to known messages only', () => {
  assert.equal(refusalKey({ error_code: 'not_humanoid', error_reason: 'hands_stuck' }), 'rig.refusal.hands_stuck')
  for (const reason of ['arms_raised', 'turned']) assert.equal(refusalKey({ error_code: 'not_humanoid', error_reason: reason }), `rig.refusal.${reason}`)
  assert.equal(refusalKey({ error_code: 'not_humanoid', error_reason: 'something new' }), null)
  assert.equal(refusalKey({ error_code: 'rig_failed', error_reason: 'hands_stuck' }), null)
  assert.equal(refusalKey(null), null)
  assert.deepEqual(warningKeys(['arms_steep', 'unknown', 'facing_back']), ['rig.humanoidWarning.arms_steep', 'rig.humanoidWarning.facing_back'])
  assert.deepEqual(warningKeys(['on_a_base']), ['rig.humanoidWarning.on_a_base'])
  assert.equal(rigLabel('2026-10-03-12h00m00s_rigged_hero_ab12cd34.glb'), 'hero_ab12cd34')
  assert.equal(rigLabel('humanoid-hero-0123456789abcdef.glb'), 'humanoid-hero-0123456789abcdef')
  assert.equal(isRigSource('2026-10-03-12h00m00s_hunyuan3d_hero.glb'), true)
  assert.equal(isRigSource('2026-10-03-12h00m00s_rigged_hero_ab12cd34.glb'), false)
  assert.equal(isRigSource('humanoid-hero-0123456789abcdef.glb'), false)
  assert.equal(isRigSource('humanoid-shaped-statue.glb'), true)
})
