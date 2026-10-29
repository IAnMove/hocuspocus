import assert from 'node:assert/strict'
import test from 'node:test'
import en from '../src/i18n/locales/en/characters.json' with { type: 'json' }
import es from '../src/i18n/locales/es/characters.json' with { type: 'json' }
import { createCharacterKit, type CharacterKit } from '../src/lib/characterKit.ts'
import { lockFaceRigMouthPlacement } from '../src/lib/characterKitFaceRig.ts'
import { faceRigPlacementSources, keptFacePlacement } from '../src/lib/faceRigPlacement.ts'

function kitWith(sources: { eyesSource?: string; mouthSource?: string; brows?: number[][] }): CharacterKit {
  const kit = createCharacterKit('Gorthak')
  kit.anchors.base = {
    mouth: { offsetX: 0, offsetY: 8, scale: 0.05, rotation: 0 },
    eyesSource: sources.eyesSource as CharacterKit['anchors'][string]['eyesSource'],
    mouthSource: sources.mouthSource as CharacterKit['anchors'][string]['mouthSource'],
    brows: sources.brows as CharacterKit['anchors'][string]['brows'],
  }
  return kit
}

test('the editor names both sources and stays quiet when the rig did not record them', () => {
  assert.equal(en.faceRig.placementSource, 'Eyes from {{eyes}}, mouth from {{mouth}}.')
  assert.equal(es.faceRig.placementSource, 'Ojos por {{eyes}}, boca por {{mouth}}.')
  assert.deepEqual(Object.keys(en.faceRig.sources), Object.keys(es.faceRig.sources))
  assert.deepEqual(faceRigPlacementSources(kitWith({ eyesSource: 'landmarks', mouthSource: 'whites' }), 'base'), {
    eyes: 'landmarks', mouth: 'whites',
  })
  assert.equal(faceRigPlacementSources(kitWith({}), 'base'), null)
  assert.equal(faceRigPlacementSources(kitWith({ eyesSource: 'guess', mouthSource: 'whites' }), 'base'), null)
  assert.equal(faceRigPlacementSources(kitWith({ eyesSource: 'hint' }), 'base'), null)
})

test('a hand-placed mouth is no longer labelled as landmarks', () => {
  const kit = kitWith({ eyesSource: 'landmarks', mouthSource: 'landmarks' })
  const locked = lockFaceRigMouthPlacement(kit, 'base', { offsetX: 1, offsetY: 2, scale: 0.2, rotation: 0 })
  assert.equal(locked.anchors.base.eyesSource, 'landmarks')
  assert.equal(locked.anchors.base.mouthSource, 'hint')
  assert.equal(keptFacePlacement(locked.anchors.base).mouthSource, 'hint')
})

test('locking the mouths keeps the placement record', () => {
  const kit = kitWith({
    eyesSource: 'landmarks',
    mouthSource: 'hint',
    brows: [[1, 2, 3, 4], [5, 6, 7, 8]],
  })
  const locked = lockFaceRigMouthPlacement(kit, 'base', { offsetX: 1, offsetY: 2, scale: 0.2, rotation: 0 })
  assert.equal(locked.anchors.base.eyesSource, 'landmarks')
  assert.equal(locked.anchors.base.mouthSource, 'hint')
  assert.deepEqual(locked.anchors.base.brows, [[1, 2, 3, 4], [5, 6, 7, 8]])
})
