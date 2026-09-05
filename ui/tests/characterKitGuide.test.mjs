import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { lockFaceRigMouthPlacement } from '../src/lib/characterKitFaceRig.ts'
import { registerWipedKitPose } from '../src/lib/characterKit.ts'
import {
  characterKitNextStep,
  characterKitOpeningTab,
  characterKitPoseLabel,
  characterKitPoseOptions,
} from '../src/features/characters/characterKitGuide.ts'

const approved = (id, source) => ({
  id, name: id, source, kind: 'image', alphaStatus: 'transparent', reviewState: 'approved',
})

test('pose labels use human names instead of ids', () => {
  assert.equal(characterKitPoseLabel('base'), 'Standing')
  assert.equal(characterKitPoseLabel('reaction'), 'Reaction')
  assert.equal(characterKitPoseLabel('pointing'), 'Pointing')
})

test('a kit with an approved body opens on mouths, not the advanced layer mapper', () => {
  const kit = {
    ...createCharacterKit('Brin'),
    base: approved('brin-base', '/api/v1/file/brin.png'),
    poses: { reaction: approved('brin-reaction', '/api/v1/file/brin-reaction.png') },
    mouth: {
      closed: { ...approved('closed', '/api/v1/file/closed.png'), kind: 'overlay' },
      wide: { ...approved('wide', '/api/v1/file/wide.png'), kind: 'overlay' },
    },
  }
  assert.equal(characterKitOpeningTab(kit), 'face-rig')
  assert.deepEqual(characterKitPoseOptions(kit).map(pose => pose.id), ['base', 'reaction'])
  const next = characterKitNextStep(kit, 'reaction')
  assert.equal(next.id, 'wipe-mouth')
  assert.match(next.title, /box/i)
  assert.match(next.detail, /Wipe mouth area/)
})

test('after wipe and lock the next action is to put the character on the scene', () => {
  let kit = {
    ...createCharacterKit('Luma'),
    base: approved('luma-base', '/api/v1/file/luma.png'),
    mouth: {
      closed: { ...approved('closed', '/api/v1/file/closed.png'), kind: 'overlay' },
      small: { ...approved('small', '/api/v1/file/small.png'), kind: 'overlay' },
    },
  }
  kit = registerWipedKitPose(kit, 'base', { ...kit.base, source: '/api/v1/file/luma-mouthless.png' })
  kit = lockFaceRigMouthPlacement(kit, 'base', { offsetX: 0, offsetY: -16, scale: .07, rotation: 0 })
  const next = characterKitNextStep(kit, 'base')
  assert.equal(next.id, 'put-on-scene')
  assert.match(next.title, /scene/i)
})

test('empty library tells the user to pick a character', () => {
  const next = characterKitNextStep(null)
  assert.equal(next.id, 'pick-character')
  assert.match(next.detail, /Luma or Brin/)
})
