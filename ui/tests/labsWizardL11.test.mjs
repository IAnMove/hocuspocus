import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

test('L11 names ACE separately from MiniMax and uses adapter prompt limits', () => {
  const bar = readFileSync(new URL('../src/features/stories/StoryMusicSettingsBar.tsx', import.meta.url), 'utf8')
  const card = readFileSync(new URL('../src/features/stories/MusicCueCard.tsx', import.meta.url), 'utf8')
  const music = readFileSync(new URL('../src/features/stories/storyLabMusic.ts', import.meta.url), 'utf8')
  const en = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/storyLab.json', import.meta.url), 'utf8'))
  const es = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/storyLab.json', import.meta.url), 'utf8'))

  assert.match(bar, /storyMusicReadyMessageKey/)
  assert.equal(bar.includes("t('music.minimaxLocalReady')"), false)
  assert.equal(en.music.aceLocalReady.includes('ACE-Step'), true)
  assert.equal(es.music.aceLocalReady.includes('ACE-Step'), true)
  assert.equal(en.music.minimaxLocalReady.includes('MiniMax Music 3'), true)
  assert.match(card, /musicPromptLimit/)
  assert.match(card, /musicCueBlock/)
  assert.match(music, /catalogEntry/)
  assert.equal(en.music.promptChars.includes('{{limit}}'), true)
  assert.equal(es.music.promptHint.includes('{{limit}}'), true)
  assert.equal(en.music.promptChars.includes('/300'), false)
})

test('L11 Series Review and Story genre/tone labels come from catalogs', () => {
  const review = readFileSync(new URL('../src/features/series/SeriesReviewPanel.tsx', import.meta.url), 'utf8')
  const overview = readFileSync(new URL('../src/features/stories/StoryOverviewTab.tsx', import.meta.url), 'utf8')
  const enSeries = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/seriesLab.json', import.meta.url), 'utf8'))
  const esSeries = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/seriesLab.json', import.meta.url), 'utf8'))
  const enStory = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/storyLab.json', import.meta.url), 'utf8'))
  const esStory = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/storyLab.json', import.meta.url), 'utf8'))

  assert.match(review, /t\('review.playAll'\)/)
  assert.match(review, /t\('review.joinClips'\)/)
  const renderActions = readFileSync(new URL('../src/features/series/SeriesRenderActions.tsx', import.meta.url), 'utf8')
  assert.match(renderActions, /t\('renderActions.generate',/)
  assert.equal(enSeries.renderActions.generate, 'Generate AI draft takes ({{count}})')
  assert.equal(esSeries.renderActions.generate, 'Generar borradores con IA ({{count}})')
  assert.equal(review.includes('>Play all<') || review.includes('>Join clips<'), false)
  assert.equal(enSeries.review.playAll, 'Play all')
  assert.equal(esSeries.review.playAll, 'Reproducir todo')
  assert.match(overview, /overview.genreTone/)
  assert.equal(enStory.overview.genreTone.adventure, 'Adventure')
  assert.equal(esStory.overview.genreTone.adventure, 'Aventura')
  assert.equal(enStory.overview.genreTone.cinematic, 'Cinematic')
  assert.equal(esStory.overview.genreTone.cinematic, 'Cinematográfico')
})

test('L11 removes the hidden music drawer without dropping song recovery', () => {
  const panel = readFileSync(new URL('../src/features/stories/StoryProductionsMusicPanel.tsx', import.meta.url), 'utf8')
  const recovery = readFileSync(new URL('../src/features/stories/storySongRecovery.ts', import.meta.url), 'utf8')
  const drawer = new URL('../src/features/stories/StoryMusicProductionLegacyDrawer.tsx', import.meta.url)
  assert.equal(existsSync(drawer), false)
  assert.equal(panel.includes('StoryMusicProductionLegacyDrawer'), false)
  assert.match(recovery, /recoverPendingStorySongs/)
  assert.match(panel, /StoryMusicProductionSong/)
})
