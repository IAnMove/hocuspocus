import assert from 'node:assert/strict'
import test from 'node:test'
import { reasonAfterLock } from '../src/i18n/disabledReasons.ts'
import { setUiLanguage } from '../src/i18n/index.ts'

test('a locked panel names the parent lock before any later cause', async () => {
  await setUiLanguage('en')
  assert.equal(
    reasonAfterLock(true, 'Wait until saving finishes', [[true, 'disabled.writeName']]),
    'Wait until saving finishes',
  )
  assert.equal(reasonAfterLock(true, undefined, []), 'This panel is locked')
  assert.equal(
    reasonAfterLock(false, undefined, [[false, 'disabled.writeName'], [true, 'disabled.actionInProgress']]),
    'Wait until the current action finishes',
  )
  assert.equal(reasonAfterLock(false, undefined, [[false, 'disabled.writeName']]), undefined)
  await setUiLanguage('es')
  assert.equal(reasonAfterLock(true, undefined, []), 'Este panel está bloqueado')
  await setUiLanguage('en')
})
