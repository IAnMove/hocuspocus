import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, characterKitStillSource } from '../src/lib/characterKit'
import { characterRestPoseKey, characterRestPoseSource, prepareCharacterRestPose } from '../src/lib/characterRestPose'
import { applyFaceRigMouthPreset } from '../src/lib/characterKitFaceRig'

function fixture() {
  const kit = createCharacterKit('Actor')
  kit.base = { id: 'base', name: 'Wiped base', source: '/wiped.png', kind: 'image', alphaStatus: 'transparent', reviewState: 'pending' }
  kit.identityReference = { ...kit.base, source: '/old-baked-mouth.png' }
  kit.mouth.closed = { ...kit.base, id: 'closed', source: '/closed.png', kind: 'overlay' }
  kit.anchors.base = { mouth: { offsetX: 2, offsetY: -20, scale: .1, rotation: 0 } }
  return kit
}

test('a saved resting composite becomes the still reference without flattening the mouth into the animation base', async () => {
  const kit = fixture()
  kit.restPose = { fingerprint: characterRestPoseKey(kit)!, asset: { ...kit.base!, source: '/composed-rest.png' } }
  assert.equal(characterKitStillSource(kit), '/composed-rest.png')
  assert.equal(kit.base!.source, '/wiped.png')
  const unchanged = await prepareCharacterRestPose(kit, 'default', async () => { throw new Error('Unnecessary upload') }, name => name)
  assert.equal(unchanged, kit)
  kit.voice = { voiceId: 'other' } as typeof kit.voice
  assert.equal(characterRestPoseSource(kit), '/composed-rest.png')
  kit.anchors.base.mouth.offsetX++
  assert.equal(characterRestPoseSource(kit), undefined)
})

test('replacing the wiped image or resting drawing invalidates the composed still; rejected assets never propagate', () => {
  const kit = fixture(), key = characterRestPoseKey(kit)
  kit.mouth.closed!.source = '/new-closed.png'
  assert.notEqual(characterRestPoseKey(kit), key)
  kit.base!.source = '/new-wipe.png'
  assert.notEqual(characterRestPoseKey(kit), key)
  kit.mouth.closed!.reviewState = 'rejected'
  assert.equal(characterRestPoseKey(kit), undefined)
})

test('changing to a four-state pack removes extra drawings from the previous style', () => {
  const kit = fixture()
  kit.mouth.bite = { ...kit.mouth.closed! }
  const next = applyFaceRigMouthPreset(kit, { id: 'classic', label: 'Classic', states: { closed: { file: 'classic/closed.png' } } })
  assert.equal(next.mouth.bite, undefined)
  assert.ok(kit.mouth.bite)
})
