import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { assessFaceRigPlacement, classifyCharacterKitAlpha, faceRigAnchorFor, faceRigGenerationRequests, faceRigOverlayPreviewStyle, faceRigPrompt, registerCleanedFaceRigAsset, registerGeneratedFaceRigAsset, setFaceRigAnchor, setFaceRigReviewState, validateFaceRigPose } from '../src/lib/characterKitFaceRig.ts'

const pose = { id: 'base', name: 'Base', source: 'base.png', kind: 'image', alphaStatus: 'opaque', reviewState: 'approved' }
const generated = state => ({ id: `generated-${state}`, name: state, source: `${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'approved' })

test('alpha classification detects a materially transparent RGBA image', () => {
  const rgba = new Uint8ClampedArray([255, 255, 255, 0, 255, 255, 255, 255, 255, 255, 255, 128, 255, 255, 255, 255])
  assert.deepEqual(classifyCharacterKitAlpha(rgba), { pixelCount: 4, transparentRatio: .5, translucentRatio: .25, opaqueRatio: .5, status: 'transparent' })
})

test('alpha classification accepts an effectively opaque image', () => {
  const rgba = new Uint8ClampedArray([0, 0, 0, 255, 1, 1, 1, 255, 2, 2, 2, 254, 3, 3, 3, 255])
  const metrics = classifyCharacterKitAlpha(rgba)
  assert.equal(metrics.pixelCount, 4)
  assert.equal(metrics.opaqueRatio, .75)
  assert.equal(metrics.status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray([0, 0, 0, 255, 1, 1, 1, 255, 2, 2, 2, 255, 3, 3, 3, 255])).status, 'opaque')
})

test('alpha classification returns unknown for invalid pixel data', () => {
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray()).status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray([0, 0, 0])).status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(/** @type {any} */ (new Uint8Array([0, 0, 0, 255]))).status, 'unknown')
})

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

test('cleaning a Face Rig overlay keeps it pending and records provenance', () => {
  const kit = registerGeneratedFaceRigAsset({ ...createCharacterKit('Luna'), base: pose }, 'wide', generated('wide'), { poseId: 'base', reference: 'base.png', prompt: 'wide prompt' })
  const cleaned = registerCleanedFaceRigAsset(kit, 'wide', {
    source: '/api/v1/file/wide.cleanup-abcd.png',
    filename: 'wide.cleanup-abcd.png',
    original: 'wide.png',
    width: 48,
    height: 24,
    alpha: { pixelCount: 4, transparentRatio: .5, translucentRatio: .25, opaqueRatio: .5, status: 'transparent' },
    method: 'rembg-u2net',
    padding: 8,
    model: 'u2net',
  })
  assert.equal(kit.mouth.wide.source, 'wide.png')
  assert.equal(cleaned.mouth.wide.source, '/api/v1/file/wide.cleanup-abcd.png')
  assert.equal(cleaned.mouth.wide.reviewState, 'pending')
  assert.equal(cleaned.mouth.wide.alphaStatus, 'transparent')
  assert.equal(cleaned.provenance.at(-1).method, 'character-kit-face-rig-cleanup')
  assert.throws(() => registerCleanedFaceRigAsset(kit, 'closed', {
    source: '/api/v1/file/closed.cleanup.png', filename: 'closed.cleanup.png', original: 'closed.png',
    width: 8, height: 8, alpha: { pixelCount: 1, transparentRatio: 1, translucentRatio: 0, opaqueRatio: 0, status: 'transparent' },
    method: 'rembg-u2net', padding: 8,
  }), /no generated closed asset/)
})

test('Face Rig anchors fall back to the legacy mouth slot and save per-state placement', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose, anchors: { base: { mouth: { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 } } } }
  assert.deepEqual(faceRigAnchorFor(kit, 'base', 'wide'), { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  const next = setFaceRigAnchor(kit, 'base', 'wide', { offsetX: 1, offsetY: -18, scale: .055, rotation: 2 })
  assert.equal(kit.anchors.base.mouthStates, undefined)
  assert.deepEqual(next.anchors.base.mouthStates.wide, { offsetX: 1, offsetY: -18, scale: .055, rotation: 2 })
  assert.deepEqual(next.anchors.base.mouth, { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  const blinked = setFaceRigAnchor(next, 'base', 'blink', { offsetX: 0, offsetY: -30.5, scale: .149, rotation: 0 })
  assert.deepEqual(blinked.anchors.base.eyes, { offsetX: 0, offsetY: -30.5, scale: .149, rotation: 0 })
  assert.equal(blinked.provenance.at(-1).method, 'character-kit-face-rig-anchor')
})

test('placement preview uses relative CSS and warns when the overlay misses the face', () => {
  const style = faceRigOverlayPreviewStyle({ offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  assert.equal(style.left, '50%')
  assert.equal(style.top, '31%')
  assert.equal(style.width, '4.1%')
  assert.equal(assessFaceRigPlacement({ offsetX: 0, offsetY: -19, scale: .041, rotation: 0 }, 'wide').ok, true)
  const huge = assessFaceRigPlacement({ offsetX: 80, offsetY: 8, scale: .9, rotation: 0 }, 'wide')
  assert.equal(huge.ok, false)
  assert.ok(huge.warnings.some(warning => /miss the face/.test(warning)))
  assert.ok(huge.warnings.some(warning => /larger than a typical viseme/.test(warning)))
})
