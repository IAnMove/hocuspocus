import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createCharacterKit, type CharacterKitLibrary } from '../../src/lib/characterKit'
import type { SeriesLibrary } from '../../src/features/series/types'

test('completed shots keep updates discreet and explain character blockers without disabling ready shots', async ({ page }) => {
  const session = await gotoApp(page)
  const series = (JSON.parse(readFileSync(new URL('../../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')) as SeriesLibrary).seriesById.series_signal
  series.allowedProductionMethods = ['animation_2d']
  const episode = Object.values(series.episodesById)[0]
  const template = episode.shots[0]
  const library: CharacterKitLibrary = { version: 1, revision: 1, activeId: '', kits: {} }
  for (const [index, character] of series.characters.entries()) {
    const kit = createCharacterKit(character.name)
    kit.base = { id: 'base', name: 'Base', source: '/fixture-body.svg', kind: 'image', alphaStatus: 'transparent', reviewState: index === 0 ? 'approved' : 'pending' }
    kit.anchors.base = { mouth: { offsetX: 0, offsetY: -20, scale: .08, rotation: 0 } }
    for (const state of ['closed', 'small', 'wide', 'round'] as const) kit.mouth[state] = {
      id: state, name: state, source: `/character-kit-presets/mouths/paper-cut/${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'approved',
    }
    library.kits[kit.id] = kit
    character.voiceProfile = { characterKitRef: { workspace: 'default', id: kit.id } }
  }
  series.assets.video = { ...Object.values(series.assets)[0], id: 'video', kind: 'video', uri: 'fixture.mp4',
    metadata: { productionMethod: 'animation_2d', sceneFilename: 'fixture.json' } }
  episode.shots = series.characters.map((character, index) => ({ ...template, id: `shot-${index}`, order: index + 1,
    productionMethod: 'animation_2d', approvedAttemptId: undefined, visibleCharacterIds: [character.id],
    dialogueBeats: [{ ...template.dialogueBeats[0], id: `beat-${index}`, characterId: character.id, text: 'Hello.' }],
    attempts: [{ ...template.attempts[0], id: `take-${index}`, status: 'completed', outputAssetIds: ['video'] }] }))
  await page.route('**/api/v1/series/**', async route => {
    expect(route.request().method()).toBe('GET')
    const path = new URL(route.request().url()).pathname
    await route.fulfill({ json: path.endsWith('/library')
      ? { schemaVersion: 1, workspace: 'default', seriesOrder: [series.id], seriesById: { [series.id]: series } }
      : path.endsWith('/recovery') ? { jobs: [] } : series })
  })
  await page.route('**/api/v1/character-kits/library**', route => route.fulfill({ json: library }))
  await page.route('**/fixture-body.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><circle cx="128" cy="128" r="100" fill="#fab"/></svg>' }))
  await page.getByRole('tab', { name: 'Series Lab', exact: true }).click()
  await page.getByRole('button', { name: '4 · Shots', exact: true }).click()
  const panel = page.getByRole('region', { name: '2D shots', exact: true })
  await expect(panel.getByText('2 2D shots already have video.')).toBeVisible()
  await expect(panel.getByRole('button', { name: /Generate all pending/ })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /Update lip sync for/ })).toBeHidden()
  await panel.getByText('Update shots after character changes').click()
  await expect(panel.getByRole('button', { name: 'Update lip sync for 1 ready shots' })).toBeEnabled()
  await expect(panel.getByText(/workshop base is unapproved/)).toBeVisible()
  await panel.getByRole('button', { name: series.characters[1].name, exact: true }).click()
  await expect(page.getByTestId('character-name')).toHaveValue(series.characters[1].name)
  await closeApp(page, session)
})
