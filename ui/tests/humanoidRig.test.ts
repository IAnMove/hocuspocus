import assert from 'node:assert/strict'
import test from 'node:test'
import type { RigCapabilities, RigProfile } from '../src/api/model3d'
import { clipIsRecommended, clipsForEngine, humanoidClipSelection, recommendedClipIds, rigFooterKey, rigHelpKey, rigJobBody } from '../src/components/Sidebar/humanoidRig'

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
    { id: 'walk', label: 'Walk', description: '' },
    { id: 'wave', label: 'Wave', description: '' },
    { id: 'dance_side', label: 'Dance Side', description: '' },
  ],
  default_spine_joints: 5,
  active_jobs: 0,
} satisfies RigCapabilities

test('humanoid engine lists its own clips and omits the spine controls', () => {
  assert.deepEqual(clipsForEngine('humanoid', capabilities, profile).map(item => item.id), ['walk', 'wave', 'dance_side'])
  assert.deepEqual(clipsForEngine('procedural', capabilities, profile).map(item => item.id), ['idle', 'walk', 'spin'])
  assert.deepEqual(recommendedClipIds('humanoid', capabilities, profile, []), ['walk', 'wave', 'dance_side'])
  assert.equal(clipIsRecommended('humanoid', 'wave', profile, ['walk', 'wave', 'dance_side']), true)
  assert.equal(clipIsRecommended('procedural', 'wave', profile, ['walk']), false)
  assert.equal(rigHelpKey('humanoid'), 'rig.humanoidHelp')
  assert.equal(rigFooterKey('humanoid'), 'rig.humanoidFooter')
  assert.equal(rigFooterKey('procedural'), 'rig.proceduralFooter')
  const body = rigJobBody({
    source: 'pet.glb', engineId: 'humanoid', rigProfileId: 'humanoid', clips: ['walk'],
    pose: 'a', spineJoints: 7, axisMode: 'x', weightFalloff: 3,
  })
  assert.equal(body.pose, 'a')
  assert.equal('spine_joints' in body, false)
  assert.deepEqual(humanoidClipSelection(['idle', 'walk', 'wave', 'dance_side']), ['walk', 'wave', 'dance_side'])
})
