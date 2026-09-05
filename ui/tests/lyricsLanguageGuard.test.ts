import assert from 'node:assert/strict'
import test from 'node:test'
import { repairLyricsLanguage, validateLyricsLanguage } from '../src/lib/lyricsLanguageGuard'

const SPANISH_OK = `[Verse]
En la red despierta el sysadmin.
[Chorus]
La noche y el código cantan.
`

test('Spanish structured lyrics stay valid', () => {
  const report = validateLyricsLanguage(SPANISH_OK, 'Español')
  assert.equal(report.ok, true)
  assert.equal(report.languageMismatch, false)
  const regional = validateLyricsLanguage(SPANISH_OK, 'Español de España')
  assert.equal(regional.ok, true)
})

test('English section tags are not contamination', () => {
  const report = validateLyricsLanguage('[Verse]\nLa noche canta.\n[Chorus]\nEl código sangra.', 'español')
  assert.equal(report.ok, true)
})

test('an accidental English chorus fails a Spanish song', () => {
  const report = validateLyricsLanguage(
    '[Verse]\nEn la red despierta el sysadmin y la noche canta.\n[Chorus]\nThe server fights through the night and we sing for our network.',
    'Español',
  )
  assert.equal(report.ok, false)
  assert.equal(report.languageMismatch, true)
})

test('Chinese or Arabic runs fail Spanish lyrics', () => {
  assert.equal(validateLyricsLanguage('[Verse]\nEn la red.\n[Chorus]\n夜晚在服务器里唱歌', 'castellano').ok, false)
  assert.equal(validateLyricsLanguage('[Verse]\nEn la red.\n[Chorus]\nالليل يغني', 'es').ok, false)
})

test('quoted English remains when protected', () => {
  const report = validateLyricsLanguage('[Chorus]\nHello, world\nLa noche nos verá.', 'Español', {
    protectedSegments: [{ kind: 'lyrics', text: 'Hello, world', language: 'en' }],
  })
  assert.equal(report.ok, true)
})

test('repair strips CJK and keeps Spanish lines', () => {
  const report = repairLyricsLanguage('[Verse]\nEn la red despierta el sysadmin.\n[Chorus]\n夜晚在服务器里唱歌', 'Español')
  assert.match(report.lyrics, /En la red despierta el sysadmin/)
  assert.equal(report.lyrics.includes('夜晚'), false)
  assert.equal(report.repaired, true)
  assert.equal(report.ok, true)
})

test('repair does not translate an English chorus', () => {
  const report = repairLyricsLanguage(
    '[Verse]\nEn la red despierta el sysadmin y la noche canta.\n[Chorus]\nThe server fights through the night and we sing for our network.',
    'Español',
  )
  assert.equal(report.ok, false)
  assert.match(report.lyrics, /The server fights through the night/)
})
