import assert from 'node:assert/strict'
import test from 'node:test'
import { setUiLanguage } from '../src/i18n/index.ts'
import { controlLabel } from '../src/i18n/controlLabel.ts'

test('controlLabel returns the same text in the active language', async () => {
  await setUiLanguage('en')
  assert.equal(controlLabel('a11y.close'), 'Close')
  assert.equal(controlLabel('a11y.downloadModel'), 'Download the model files')
  assert.equal(controlLabel('disabled.actionInProgress'), 'Wait until the current action finishes')
  assert.equal(controlLabel('disabled.chooseModel'), 'Choose a model first')
  await setUiLanguage('es')
  assert.equal(controlLabel('a11y.close'), 'Cerrar')
  assert.equal(controlLabel('a11y.downloadModel'), 'Descargar los archivos del modelo')
  assert.equal(controlLabel('disabled.actionInProgress'), 'Espera a que termine la acción en curso')
  assert.equal(controlLabel('disabled.writeName'), 'Escribe primero un nombre')
  await setUiLanguage('en')
})
