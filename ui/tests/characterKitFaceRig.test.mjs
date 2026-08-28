import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { faceRigGenerationRequests, faceRigPrompt, registerGeneratedFaceRigAsset, setFaceRigReviewState, validateFaceRigPose } from '../src/lib/characterKitFaceRig.ts'

const pose = { id: 'base', name: 'Base', source: 'base.png', kind: 'image', alphaStatus: 'opaque', reviewState: 'approved' }
const generated = state => ({ id: `generated-${state}`, name: state, source: `${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'approved' })

test('Face Rig validates a persistent approved base or pose', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  assert.equal(validateFaceRigPose(kit).pose.source, 'base.png')
  assert.throws(() => validateFaceRigPose({ ...kit, base: { ...pose, reviewState: 'pending' } }), /Review and approve/)
  assert.throws(() => validateFaceRigPose({ ...kit, base: { ...pose, source: 'blob:temporary' } }), /persistent pose source/)
})

test('Face Rig produces five neutral identity-preserving generation requests', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const requests = faceRigGenerationRequests(kit, 'base', 'a shy schoolgirl with red braids')
  assert.deepEqual(requests.map(request => request.state), ['closed', 'small', 'wide', 'round', 'blink'])
  assert.ok(requests.every(request => request.reference === 'base.png' && request.prompt.includes('a shy schoolgirl with red braids')))
  assert.ok(requests.every(request => request.prompt.includes('ONLY') && request.prompt.includes('transparent') && request.prompt.includes('no full character')))
  assert.match(faceRigPrompt(kit, 'blink'), /closed eyelids/)
  assert.match(faceRigPrompt(kit, 'wide'), /mouth overlay sprite/)
})

test('registering and reviewing a generated state is immutable and records provenance', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const next = registerGeneratedFaceRigAsset(kit, 'wide', generated('wide'), { poseId: 'base', reference: 'base.png', prompt: 'wide prompt' })
  assert.equal(kit.mouth.wide, undefined)
  assert.equal(next.mouth.wide.reviewState, 'pending')
  assert.equal(next.provenance[0].method, 'character-kit-face-rig')
  const approved = setFaceRigReviewState(next, 'wide', 'approved')
  assert.equal(next.mouth.wide.reviewState, 'pending')
  assert.equal(approved.mouth.wide.reviewState, 'approved')
})

test('blink is registered in eyes and rejects transient generated sources', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const next = registerGeneratedFaceRigAsset(kit, 'blink', generated('blink'), { poseId: 'base', reference: 'base.png', prompt: 'blink prompt' })
  assert.equal(next.eyes.blink.reviewState, 'pending')
  assert.throws(() => registerGeneratedFaceRigAsset(kit, 'round', { ...generated('round'), source: 'blob:temp' }, { poseId: 'base', reference: 'base.png', prompt: 'round' }), /persistent source/)
})
