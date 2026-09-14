import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

test('Series Lab L10 keeps five destinations and groups canon without dropping data', () => {
  const panel = readFileSync(new URL('../src/features/series/SeriesLabPanel.tsx', import.meta.url), 'utf8')
  const canon = readFileSync(new URL('../src/features/series/SeriesCanonPanel.tsx', import.meta.url), 'utf8')
  const en = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/seriesLab.json', import.meta.url), 'utf8'))
  const es = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/seriesLab.json', import.meta.url), 'utf8'))

  assert.match(panel, /id: 'setup'/)
  assert.match(panel, /id: 'canon'/)
  assert.match(panel, /id: 'episode'/)
  assert.match(panel, /id: 'shots'/)
  assert.match(panel, /id: 'review'/)
  assert.equal(en.tabs.setup.includes('Preparation'), true)
  assert.equal(es.tabs.canon.includes('Biblia'), true)
  assert.equal(es.tabs.review.includes('Resultados'), true)

  assert.match(canon, /'world' \| 'characters' \| 'locations' \| 'continuity' \| 'advanced'/)
  assert.match(canon, /tab === 'characters' && <SectionCard title=\{t\('canon.relationshipsTitle'\)/)
  assert.match(canon, /tab === 'continuity'/)
  assert.match(canon, /tab === 'advanced' && <SectionCard title=\{t\('canon.propsTitle'\)/)
  assert.match(canon, /<SeriesVoiceFields/)
  assert.match(en.canon.voicesDescription, /do not control MiniMax H3/i)
  assert.match(es.canon.voicesDescription, /no controlan MiniMax H3/i)
})

test('Series shots keep a compact face and hide IDs behind advanced details', () => {
  const shots = readFileSync(new URL('../src/features/series/SeriesShotsPanel.tsx', import.meta.url), 'utf8')
  assert.match(shots, /shot\.action \|\| shot\.framing/)
  assert.match(shots, /dialogueBeats\.map/)
  assert.match(shots, /native\.editShot/)
  assert.match(shots, /<details/)
  const draft = readFileSync(new URL('../src/features/series/SeriesShotDraftFields.tsx', import.meta.url), 'utf8')
  const proposal = readFileSync(new URL('../src/features/series/SeriesEpisodeProposalReview.tsx', import.meta.url), 'utf8')
  assert.match(proposal, /<SeriesShotDraftFields/)
  assert.match(draft, /proposal\.action/)
})
