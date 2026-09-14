import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createCharacterKit, type CharacterKitLibrary } from '../../src/lib/characterKit'
import type { SeriesLibrary, SeriesProject } from '../../src/features/series/types'

test('Series saves voice and pending mouths together, returns to the character and opens the next one', async ({ page }) => {
  const session = await gotoApp(page)
  let series: SeriesProject = (JSON.parse(readFileSync(new URL('../../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')) as SeriesLibrary).seriesById.series_signal
  const kit = createCharacterKit(series.characters[0].name)
  kit.base = { id: 'base', name: 'Base', source: '/save-fixture.svg', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
  let library: CharacterKitLibrary = { version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } }
  series = { ...series, characters: series.characters.map((character, index) => ({ ...character, referenceAssetIds: [], primaryReferenceAssetId: undefined,
    voiceProfile: index === 0 ? { characterKitRef: { workspace: 'default', id: kit.id } } : {} })) }
  let writes = 0
  await page.route('**/save-fixture.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><circle cx="128" cy="128" r="100" fill="#fab"/></svg>' }))
  await page.route('**/api/v1/series/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() === 'PUT') {
      const body = request.postDataJSON()
      expect(body.baseRevision).toBe(series.revision)
      series = { ...body.series, revision: series.revision + 1 }
    }
    const body = path.endsWith('/library') ? { schemaVersion: 1, workspace: 'default', seriesOrder: [series.id], seriesById: { [series.id]: series } }
      : path.endsWith('/recovery') ? { jobs: [] } : series
    await route.fulfill({ json: body })
  })
  await page.route('**/api/v1/character-kits/library**', async route => {
    const request = route.request()
    if (request.method() === 'PATCH') {
      const body = request.postDataJSON()
      expect(body.baseRevision).toBe(library.revision)
      expect(body.kit.voice.voiceId).toBe('serena')
      expect(Object.keys(body.kit.mouth)).toHaveLength(4)
      expect(Object.values(body.kit.mouth).every(mouth => (mouth as { reviewState: string }).reviewState === 'pending')).toBe(true)
      library = { ...library, revision: library.revision + 1, kits: { ...library.kits, [kit.id]: body.kit } }
      writes++
    }
    await route.fulfill({ json: library })
  })
  await page.getByRole('tab', { name: 'Series Lab', exact: true }).click()
  await page.getByRole('button', { name: '2 · Bible', exact: true }).click()
  await page.getByRole('button', { name: 'Characters', exact: true }).click()
  const first = page.getByRole('region', { name: `Voice and lip sync for ${series.characters[0].name}` })
  await first.getByRole('button', { name: 'Configure in Character Creator' }).click()
  await page.getByRole('button', { name: 'Configure 2D mouth and lip sync' }).click()
  const workshop = page.getByRole('region', { name: 'Prepare 2D speech', exact: true })
  await workshop.getByRole('button', { name: 'Use pack', exact: true }).click()
  await page.getByTestId('character-voice').selectOption('serena')
  await page.getByRole('button', { name: 'Save everything and return to Series Lab' }).click()
  await expect(first).toBeVisible()
  expect(writes).toBe(1)
  expect(series.characters[0].voiceProfile?.characterKitRef?.id).toBe(kit.id)
  const second = page.getByRole('region', { name: `Voice and lip sync for ${series.characters[1].name}` })
  await second.getByRole('button', { name: 'Configure in Character Creator' }).click()
  await expect(page.getByTestId('character-name')).toHaveValue(series.characters[1].name)
  expect(writes).toBe(1)
  await closeApp(page, session)
})
