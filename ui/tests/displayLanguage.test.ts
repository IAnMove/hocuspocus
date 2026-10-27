import assert from 'node:assert/strict'
import test from 'node:test'
import { displayLanguageName } from '../src/i18n/displayLanguage'

test('language names follow the UI language and unknown text stays stored', () => {
  assert.equal(displayLanguageName('English', 'en'), 'English')
  assert.equal(displayLanguageName('English', 'es'), 'inglés')
  assert.equal(displayLanguageName('Español', 'en'), 'Spanish')
  assert.equal(displayLanguageName('Klingon Trade Pidgin', 'es'), 'Klingon Trade Pidgin')
})
