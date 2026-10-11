import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document'
import { propSlot } from '../src/features/scene3d/PropLibraryPanel'
test('prop metadata, alpha grounding and billboard survive editing', () => {
  const doc = createDefaultScene3DDocument()
  const slot = propSlot({ id: 'cup', name: 'Cup', description: '', heightM: .2, file: 'cup.png', style: 'paper', approved: true }, 'demo')
  slot.billboard = true; slot.position = [0,.75,0]
  doc.slots.push(slot)
  const kept = parseScene3DDocument(doc)!.slots.at(-1)!
  assert.equal(kept.scale, .1); assert.equal(kept.position[1], .75)
  assert.equal(kept.imageLook?.grounded, true); assert.equal(kept.billboard, true)
  assert.equal(kept.setItem?.heightM, .2)
})
