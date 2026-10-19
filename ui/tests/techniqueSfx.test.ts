import assert from 'node:assert/strict'
import test from 'node:test'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { isCameraTechnique, techniqueCategory } from '../src/features/scene3d/techniqueTemplates.ts'
import { applyScene3DTemplate, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { templateTraits } from '../src/features/scene3d/templateTraits.ts'
import type { Scene3DTemplateId } from '../src/features/scene3d/types.ts'

const build = (id: Scene3DTemplateId) => parseScene3DDocument(structuredClone(applyScene3DTemplate(id)))!

test('the honest technique cards carry the screen effect that does their thing, and it survives the parser', () => {
  const expected: Array<[Scene3DTemplateId, string, number]> = [
    ['cine-film-grain', 'film_grain', 0.8], ['cine-lens-flare', 'light_rays', 1], ['cine-anamorphic-flare', 'light_rays', 1.2],
    ['cine-chromatic-aberration', 'glitch', 0.3], ['cine-vignette', 'vignette', 1], ['cine-light-leak', 'light_rays', 0.7], ['cine-datamosh', 'glitch', 1],
  ]
  for (const [id, kind, intensity] of expected) {
    const doc = build(id)
    assert.deepEqual(doc.sfx.map(cue => [cue.id, cue.kind, cue.start, cue.end, cue.intensity]), [[`${id}-fx-0`, kind, 0, doc.duration, intensity]], id)
    const traits = templateTraits(doc, { category: TEMPLATE_CATEGORIES[id], family: techniqueCategory(id) })
    assert.ok(traits.moving.includes('effects') && !traits.still, id)
  }
  assert.ok(templateTraits(build('cine-datamosh'), { family: 'effects' }).uses.includes('transition'), 'a short cut carried by its glitch')
  assert.equal(build('cine-stop-motion').motionStep, 3)
  assert.equal(build('cine-rack-focus').sfx.length, 0, 'a card the renderer cannot do stays plain')
})

test('the three-shot and the group shot stand a third figure in the prop slot around the centred subject', () => {
  for (const [id, spread] of [['cine-three-shot', 1.3], ['cine-group-shot', 1.6]] as const) {
    const doc = build(id)
    const figures = doc.slots.filter(slot => slot.media === 'model3d')
    assert.equal(figures.length, 3, id)
    assert.deepEqual(figures.map(slot => slot.slot), ['subject_1', 'subject_2', 'prop'])
    assert.deepEqual(figures[0].position, [0, 0, 0])
    assert.equal(figures[1].position[0], -spread)
    assert.equal(figures[2].position[0], spread)
    assert.ok(figures[1].rotationY > 0 && figures[2].rotationY < 0, 'the ends turn in')
    assert.equal(doc.camera.framing?.targetSlot, 'subject_1')
    assert.equal(templateTraits(doc, { family: 'framing' }).props, 1)
  }
})

test('camera cards are the camera families of the technique set', () => {
  assert.equal(techniqueCategory('cine-crane-up'), 'camera-movement')
  assert.equal(techniqueCategory('dance-orbit'), undefined)
  assert.ok(isCameraTechnique('cine-crane-up') && isCameraTechnique('cine-three-shot') && isCameraTechnique('cine-low-angle'))
  assert.ok(!isCameraTechnique('cine-rembrandt') && !isCameraTechnique('cine-teal-orange') && !isCameraTechnique('dance-orbit'))
})
