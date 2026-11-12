import assert from 'node:assert/strict'
import test from 'node:test'
import { setUiLanguage } from '../src/i18n/index.ts'
import { controlChoice, controlLabel, controlReason, firstControlReason } from '../src/i18n/controlLabel.ts'

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

test('controlReason is present only while the cause is true', async () => {
  await setUiLanguage('en')
  assert.equal(controlReason(false, 'disabled.actionInProgress'), undefined)
  assert.equal(controlReason(true, 'disabled.actionInProgress'), 'Wait until the current action finishes')
  await setUiLanguage('es')
  assert.equal(controlReason(true, 'disabled.profileLoading'), 'Espera a que cargue el perfil de producción')
  await setUiLanguage('en')
})

test('controlChoice picks one name', async () => {
  await setUiLanguage('en')
  assert.equal(controlChoice(true, 'disabled.waitForVoice', 'a11y.voiceOptions'), 'Wait until the text is ready')
  assert.equal(controlChoice(false, 'disabled.waitForVoice', 'a11y.voiceOptions'), 'More voice options')
})

test('firstControlReason returns the first missing cause', async () => {
  await setUiLanguage('en')
  assert.equal(firstControlReason([[false, 'disabled.actionInProgress'], [true, 'disabled.chooseModel']]), 'Choose a model first')
  assert.equal(firstControlReason([[false, 'disabled.chooseModel'], [false, 'disabled.writeName']]), undefined)
  await setUiLanguage('es')
  assert.equal(firstControlReason([[true, 'disabled.writeName'], [true, 'disabled.writeDescription']]), 'Escribe primero un nombre')
  await setUiLanguage('en')
})
