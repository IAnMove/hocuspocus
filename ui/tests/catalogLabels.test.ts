import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { ensureUiI18n } from '../src/i18n'
import { narrativeCopy, proceduralClipCopy, proceduralCategory, rigEngineCopy, rigProfileCopy } from '../src/lib/catalogLabels'

ensureUiI18n()

const english = {
  id: 'inner-thought',
  title: 'Inner thought',
  description: 'A three-quarter medium close-up for voice-over and a contemplative beat.',
}

test('narrative template names translate by id and unknown ids keep the English data', () => {
  const en = i18n.getFixedT('en', 'studio')
  const es = i18n.getFixedT('es', 'studio')
  assert.equal(narrativeCopy(en, english).title, 'Inner thought')
  assert.equal(narrativeCopy(es, english).title, 'Pensamiento interior')
  assert.equal(narrativeCopy(es, english).description, 'Plano medio corto en tres cuartos para voz en off y un momento contemplativo.')
  assert.deepEqual(
    narrativeCopy(es, { id: 'not-a-template', title: 'Kept title', description: 'Kept description' }),
    { title: 'Kept title', description: 'Kept description' },
  )
})

test('procedural rig profiles, clips, categories and engines translate by id', () => {
  const en = i18n.getFixedT('en', 'studio')
  const es = i18n.getFixedT('es', 'studio')
  const clip = { id: 'idle', label: 'Idle Sway', description: 'Gentle side-to-side spine sway, stronger toward the top.' }
  assert.equal(proceduralClipCopy(en, clip).label, 'Idle Sway')
  assert.equal(proceduralClipCopy(es, clip).label, 'Balanceo en reposo')
  assert.equal(rigProfileCopy(es, { id: 'prop', label: 'Prop / object', description: 'Simple pickups, logos and softly deforming standalone objects.' }).label, 'Objeto / accesorio')
  assert.equal(rigProfileCopy(en, { id: 'prop', label: 'Prop / object', description: 'ignored' }).label, 'Prop / object')
  assert.equal(proceduralCategory(es, 'Locomotion'), 'Locomoción')
  assert.equal(proceduralCategory(en, 'Locomotion'), 'Locomotion')
  assert.equal(proceduralCategory(es, 'BrandNew'), 'BrandNew')
  const engine = rigEngineCopy(es, {
    id: 'procedural',
    label: 'Procedural (fast)',
    description: 'Spine-chain skeleton with distance-based skinning. Works on any object; no extra downloads.',
    install_hint: 'Run Update in Pinokio to add procedural rigging to the app environment.',
  })
  assert.equal(engine.label, 'Procedural (rápido)')
  assert.equal(engine.installHint, 'Ejecuta Actualizar en Pinokio para añadir el rigging procedural al entorno de la aplicación.')
  assert.equal(rigEngineCopy(en, { id: 'future', label: 'Future engine', description: 'Server text', install_hint: null }).label, 'Future engine')
  assert.equal(rigEngineCopy(en, { id: 'future', label: 'Future engine', description: 'Server text', install_hint: 'Keep this' }).installHint, 'Keep this')
})
