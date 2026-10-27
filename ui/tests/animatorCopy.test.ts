import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { ensureUiI18n } from '../src/i18n'

ensureUiI18n()

test('scene animator names and the motion-JSON help follow the active language', () => {
  const en = i18n.getFixedT('en', 'scene3d')
  const es = i18n.getFixedT('es', 'scene3d')
  assert.equal(en('cameraPresets.camera-locked'), 'Locked shot')
  assert.equal(es('cameraPresets.camera-handheld'), 'Cámara en mano · temblor')
  assert.equal(es('cameraPresets.camera-whip-pan'), 'Paneo rápido · temblor')
  assert.equal(en('motionPresets.vibrate'), 'Vibrating ship')
  assert.equal(es('motionPresets.vibrate'), 'Nave vibrando')
  assert.equal(es('animator.importedScene'), 'Escena importada')
  assert.equal(en('animator.defaultEvent'), 'Event')
  assert.equal(es('animator.photoCamera', { label: 'Ken Burns · izquierda' }), 'Cámara fotográfica · Ken Burns · izquierda')
  assert.match(en('animator.motionJsonHelp'), /Return only valid HocusPocus Scene Animator motion JSON/)
  assert.match(es('animator.motionJsonHelp'), /Devuelve solo JSON de movimiento válido/)
  assert.match(es('animator.motionJsonHelp'), /"curve":"dramatic"/)
})
