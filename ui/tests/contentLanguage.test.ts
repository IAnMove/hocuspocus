import assert from 'node:assert/strict'
import { test } from 'node:test'
import { setUiLanguage } from '../src/i18n/index.ts'
import { contentLanguageForUi } from '../src/lib/contentLanguage.ts'
import { explicitMusicLanguage, outlineBeats } from '../src/lib/labHelpers.ts'
import { normalizeSeriesProject } from '../src/features/series/model.ts'
import { createStoryProject, normalizeStoryProject } from '../src/features/stories/model.ts'
import { resolveSongLyricsLanguage } from '../src/features/stories/songLanguage.ts'
import { useStore } from '../src/stores/useStore.ts'

test('new stories follow the UI language and a saved language stays put', async () => {
  await setUiLanguage('en')
  assert.deepEqual(contentLanguageForUi(), {
    language: 'English', spokenLanguage: 'English', code: 'en',
  })
  const created = createStoryProject()
  assert.equal(created.language, 'English')
  assert.equal(created.spokenLanguage, 'English')
  assert.equal(created.languageIntent.contentLanguage, 'English')

  const saved = normalizeStoryProject({
    id: 'saved-es', title: 'Guardada', language: 'Español', spokenLanguage: 'Español de España',
  })
  assert.equal(saved.language, 'Español')
  assert.equal(saved.spokenLanguage, 'Español de España')
  assert.equal(saved.languageIntent.contentLanguage, 'Español')

  const missing = normalizeStoryProject({ id: 'missing', title: 'No language' })
  assert.equal(missing.language, 'English')
  assert.equal(missing.spokenLanguage, 'English')

  await setUiLanguage('es')
  assert.equal(createStoryProject().language, 'Español')
  assert.equal(createStoryProject().spokenLanguage, 'Español de España')
  assert.equal(normalizeStoryProject({ id: 'missing-es', title: 'Sigue vacía' }).language, 'English')
  await setUiLanguage('en')
})

test('an empty lyric language follows the UI language and an explicit request still wins', async () => {
  await setUiLanguage('en')
  assert.equal(explicitMusicLanguage(''), 'English')
  assert.equal(explicitMusicLanguage('fr'), 'Français')
  assert.equal(resolveSongLyricsLanguage({}), 'English')
  assert.equal(resolveSongLyricsLanguage({ request: 'escribe la letra en español' }), 'Español')
  assert.equal(resolveSongLyricsLanguage({ fallback: 'Français' }), 'Français')
  assert.equal(outlineBeats([], '', '')[0].startsWith('Opening:'), true)

  await setUiLanguage('es')
  assert.equal(resolveSongLyricsLanguage({}), 'Español')
  assert.equal(explicitMusicLanguage(''), 'Español')
  assert.equal(outlineBeats([], '', '')[0].startsWith('Inicio:'), true)
  await setUiLanguage('en')
})

test('series normalization keeps a saved language and fills a missing one with English', () => {
  const missing = normalizeSeriesProject({ id: 'series-missing', title: 'Untitled' })
  assert.equal(missing?.language, 'English')
  assert.equal(missing?.spokenLanguage, 'English')
  const saved = normalizeSeriesProject({
    id: 'series-saved', title: 'Valle', language: 'Español', spokenLanguage: 'Español de España',
  })
  assert.equal(saved?.language, 'Español')
  assert.equal(saved?.spokenLanguage, 'Español de España')
})

test('director reset uses the UI language at that moment', async () => {
  await setUiLanguage('es')
  useStore.getState().directorReset()
  assert.equal(useStore.getState().directorSpokenLanguage, 'Español de España')
  await setUiLanguage('en')
  useStore.getState().directorReset()
  assert.equal(useStore.getState().directorSpokenLanguage, 'English')
})
