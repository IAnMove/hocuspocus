import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { canonicalLyricsLanguage, repairLyricsLanguage, validateLyricsLanguage } from '../src/lib/lyricsLanguageGuard'

const corpus = JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../tests/fixtures/lyrics_language_corpus.json'),
  'utf8',
))

for (const item of corpus.cases) {
  test(`corpus ${item.id}`, () => {
    const options = {
      protectedSegments: item.protected,
      instrumental: Boolean(item.instrumental),
    }
    const report = item.repair
      ? repairLyricsLanguage(item.lyrics, item.language, options)
      : validateLyricsLanguage(item.lyrics, item.language, options)
    assert.equal(report.verdict, item.verdict)
    assert.equal(report.ok, item.verdict === 'valid')
    if (item.preserve_original) {
      assert.equal(report.lyrics, item.lyrics)
      assert.ok(report.proposal !== undefined)
    }
  })
}

test('empty vocal lyrics are invalid', () => {
  const report = validateLyricsLanguage('', 'Español')
  assert.equal(report.verdict, 'invalid')
  assert.equal(report.ok, false)
})

test('Estonian is not scored as Spanish', () => {
  assert.equal(canonicalLyricsLanguage('Estonian'), 'et')
  const report = validateLyricsLanguage('[Verse]\nLa noche canta.\n', 'Estonian')
  assert.equal(report.verdict, 'unevaluable')
})

test('English requested as French is unevaluable', () => {
  const report = validateLyricsLanguage('[Verse]\nThe night sings through the server.', 'français')
  assert.equal(canonicalLyricsLanguage('français'), 'fr')
  assert.equal(report.verdict, 'unevaluable')
})

test('missing protected span is invalid even when the language is unevaluable', () => {
  const report = validateLyricsLanguage('[Chorus]\nLa noche nos verá.\n', 'français', {
    protectedSegments: [{ kind: 'lyrics', text: 'Hello, world', language: 'en' }],
  })
  assert.equal(report.verdict, 'invalid')
  assert.equal(report.ok, false)
  assert.equal(report.reasons.some(reason => reason.includes('verbatim')), true)
})

test('repair keeps the original lyric', () => {
  const original = '[Verse]\nEn la red despierta el sysadmin.\n[Chorus]\n夜晚在服务器里唱歌'
  const report = repairLyricsLanguage(original, 'Español')
  assert.equal(report.lyrics, original)
  assert.equal(report.lyrics.includes('夜晚'), true)
  assert.equal((report.proposal || '').includes('夜晚'), false)
})
