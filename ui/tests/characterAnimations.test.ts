import assert from 'node:assert/strict'
import test from 'node:test'
import {
  controlsForCard, findKitAnimationBySheet,
  ANIMATION_SHEET, animationDef, animationDefs, animationFrame, animationGroups, animationReference, animationState, animationsOf,
  kitStyleId, localized, reviewKitAnimation, sheetCellStyle, templateControls, withKitAnimation, withoutKitAnimation, type KitAnimation,
} from '../src/lib/characterAnimations.ts'
import { createCharacterKit } from '../src/lib/characterKit.ts'

const made = (changes: Partial<KitAnimation> = {}): Omit<KitAnimation, 'reviewState'> => ({
  sheet: { source: '/api/v1/file/walk-sheet.png?workspace=w', width: 1480, height: 640, count: 4, columns: 4, rows: 1, cell: { width: 370, height: 640 } },
  frames: [{ id: 'contact', source: '/api/v1/file/c.png' }], fps: 4, loop: 'loop', facing: 'right', ...changes,
})
const kit = () => ({ ...createCharacterKit('Ana'), base: { id: 'ana-base', name: 'Ana', source: '/api/v1/file/ana.png', kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const } })

test('the catalog groups cycles, gestures and anime expressions, each with poses to make', () => {
  assert.deepEqual(animationGroups.map(group => group.id), ['cycle', 'gesture', 'expression'])
  assert.ok(animationsOf('expression').length >= 8 && animationsOf('cycle').map(item => item.id).includes('walk'))
  for (const def of animationDefs) {
    assert.ok(def.poses.length >= 1 && def.poses.length <= ANIMATION_SHEET.maxPoses, def.id)
    assert.ok(def.poses.every(pose => pose.prompt && pose.label.es && pose.label.en), def.id)
  }
  assert.equal(animationDef('walk')?.facing, 'right')
  assert.equal(localized(animationDef('angry')!.title, 'es-ES'), 'Enfado')
  assert.equal(localized(animationDef('angry')!.title, 'en'), 'Angry')
})

test('a made animation joins the kit as pending, with its provenance, and is reviewed or deleted without touching the rest', () => {
  const base = kit()
  assert.equal(animationState(base, 'walk'), 'none')
  const stamp = new Date('2026-10-13T20:00:00Z')
  const pending = withKitAnimation(base, 'walk', made({ model: 'qwen_image_21' }), stamp)
  assert.equal(animationState(pending, 'walk'), 'pending')
  assert.equal(pending.animations!.walk.createdAt, stamp.toISOString())
  assert.deepEqual(pending.provenance.at(-1), { method: 'character-animation-make', animation: 'walk', frames: ['contact'], model: 'qwen_image_21' })
  assert.equal(base.animations, undefined, 'the kit it came from is not changed')
  const approved = reviewKitAnimation(pending, 'walk', 'approved', stamp)
  assert.equal(animationState(approved, 'walk'), 'approved')
  assert.throws(() => reviewKitAnimation(base, 'walk', 'approved'), /no walk animation/)
  const second = withKitAnimation(approved, 'wave', made({ loop: 'pingpong' }), stamp)
  assert.deepEqual(Object.keys(withoutKitAnimation(second, 'walk').animations!), ['wave'])
  assert.equal(withoutKitAnimation(approved, 'walk').animations, undefined)
})

test('poses are made from the character\'s own picture and in its style preset', () => {
  assert.equal(animationReference(kit()), '/api/v1/file/ana.png')
  const identity = { ...kit(), identityReference: { ...kit().base!, source: '/api/v1/file/identity.png' } }
  assert.equal(animationReference(identity), '/api/v1/file/identity.png')
  assert.equal(animationReference({ ...kit(), base: { ...kit().base!, source: 'blob:abc' } }), undefined)
  assert.equal(animationReference(createCharacterKit('Empty')), undefined)
  assert.equal(kitStyleId({ ...kit(), provenance: [{ method: 'character-style-create', style: 'paper-cutout' }] }), 'paper-cutout')
  assert.equal(kitStyleId(kit()), undefined)
})

test('the preview picks the cell a scene would: loop wraps, pingpong turns back, once holds the last', () => {
  const play = (loop: KitAnimation['loop'], count = 4, fps = 4) => [0, .25, .5, .75, 1, 1.25, 1.5, 1.75, 2, 5].map(seconds => animationFrame({ fps, loop, sheet: { count } }, seconds))
  assert.deepEqual(play('loop'), [0, 1, 2, 3, 0, 1, 2, 3, 0, 0])
  assert.deepEqual(play('pingpong'), [0, 1, 2, 3, 2, 1, 0, 1, 2, 2])
  assert.deepEqual(play('once'), [0, 1, 2, 3, 3, 3, 3, 3, 3, 3])
  assert.equal(animationFrame({ fps: 4, loop: 'loop', sheet: { count: 1 } }, 3), 0)
})

test('one cell of the sheet is shown by scaling the sheet to its grid and shifting it', () => {
  const sheet = { source: '/api/v1/file/s.png', columns: 4, rows: 2 }
  assert.deepEqual(sheetCellStyle(sheet, 0), { backgroundImage: 'url("/api/v1/file/s.png")', backgroundRepeat: 'no-repeat', backgroundSize: '400% 200%', backgroundPosition: '0% 0%' })
  assert.equal(sheetCellStyle(sheet, 3).backgroundPosition, '100% 0%')
  assert.equal(sheetCellStyle(sheet, 5).backgroundPosition, `${(1 / 3) * 100}% 100%`)
  assert.equal(sheetCellStyle({ ...sheet, columns: 1, rows: 1 }, 0).backgroundPosition, '0% 0%')
})

test('a made animation tells the Video 2D card that plays it which controls to use', () => {
  assert.deepEqual(templateControls(made({ fps: 4 }) as KitAnimation, 'walk-cycle-sheet'), { frames: 4, columns: 4, facing: 'right', step: .5 })
  assert.equal(templateControls(made({ facing: 'left', fps: 8 }) as KitAnimation, 'walk-cycle-sheet').facing, 'left')
  assert.equal(templateControls(made({ fps: 1 }) as KitAnimation, 'walk-cycle-sheet').step, 1, 'a step stays inside the card\'s range')
  assert.deepEqual(templateControls(made({ fps: 3, loop: 'once', facing: 'front' }) as KitAnimation, 'character-reaction'), { frames: 4, columns: 4, fps: 3, loop: 'once' })
})

test('a sheet picked in a template slot is found among the characters\' animations by its file name', () => {
  const ana = withKitAnimation(kit(), 'walk', made())
  const found = findKitAnimationBySheet([createCharacterKit('Other'), ana], 'walk-sheet.png')
  assert.equal(found?.kit.name, 'Ana')
  assert.equal(found?.id, 'walk')
  assert.equal(findKitAnimationBySheet([ana], 'another.png'), undefined)
  assert.equal(findKitAnimationBySheet([ana], undefined), undefined)
  const spaced = withKitAnimation(kit(), 'wave', made({ sheet: { ...made().sheet, source: '/api/v1/file/Ana%20wave-sheet.png?workspace=w' } }))
  assert.equal(findKitAnimationBySheet([spaced], 'Ana wave-sheet.png')?.id, 'wave')
})

test('a card is given only the controls it has, with values it accepts', () => {
  const walk = { frames: { kind: 'number', min: 3, max: 12 }, columns: { kind: 'number', min: 1, max: 12 }, facing: { kind: 'choice', options: ['right', 'left'] }, step: { kind: 'number', min: .3, max: 1 } }
  assert.deepEqual(controlsForCard(made({ fps: 4 }) as KitAnimation, 'walk-cycle-sheet', walk), { frames: 4, columns: 4, facing: 'right', step: .5 })
  assert.deepEqual(controlsForCard(made({ facing: 'left' }) as KitAnimation, 'walk-cycle-sheet', walk).facing, 'left')
  const reaction = { frames: { kind: 'number', min: 1, max: 12 }, columns: { kind: 'number', min: 1, max: 12 }, fps: { kind: 'number', min: 1, max: 12 }, loop: { kind: 'choice', options: ['once', 'loop', 'pingpong'] } }
  assert.deepEqual(controlsForCard(made({ fps: 3, loop: 'pingpong', sheet: { ...made().sheet, count: 2, columns: 2 } }) as KitAnimation, 'character-reaction', reaction), { frames: 2, columns: 2, fps: 3, loop: 'pingpong' })
  // Two poses are out of range for the walk card (at least 3), and a card without `fps` never gets one.
  assert.equal(controlsForCard(made({ sheet: { ...made().sheet, count: 2 } }) as KitAnimation, 'walk-cycle-sheet', walk).frames, undefined)
  assert.equal('fps' in controlsForCard(made() as KitAnimation, 'character-reaction', { frames: reaction.frames }), false)
})
