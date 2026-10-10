import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createStoryProject } from '../../src/features/stories/model'
import type { StoryLibraryData } from '../../src/features/stories/library'
import type { SeriesLibrary } from '../../src/features/series/types'

test('Story coaching saves manual decisions and editable proposals across reload, on mobile', async ({ page }) => {
  test.setTimeout(60000)
  const session = await gotoApp(page)
  const story = createStoryProject()
  story.title = 'Harbour of debts'
  story.language = 'English'
  let library: StoryLibraryData = { version: 2, revision: 0, activeId: story.id, projects: { [story.id]: story } }
  await page.route('**/api/v1/stories/library**', async route => {
    const request = route.request()
    if (request.method() !== 'GET') {
      const body = request.postDataJSON()
      library = body.project ? { ...library, projects: { ...library.projects, [body.project.id]: body.project } } : body.library
      library.revision += 1
    }
    await route.fulfill({ json: library })
  })
  const calls: Record<string, unknown>[] = []
  await page.route('**/api/v1/writing-guide/propose', async route => {
    calls.push(route.request().postDataJSON())
    await route.fulfill({ json: { suggestions: [
      { field: 'synopsis', value: 'The captain chooses her crew over her title.', reason: 'Her choice changes the outcome.' },
    ], examples: [], review: [], usage: null, elapsedSeconds: 0.1, provider: 'simulated', model: 'fixture' } })
  })
  const openStory = async () => {
    await page.getByRole('button', { name: 'Studios', exact: true }).click()
    await page.getByRole('tab', { name: 'Story Lab', exact: true }).click()
  }
  await openStory()
  const guide = page.getByTestId('writing-guide').first()
  await guide.locator('summary').click()
  await guide.getByRole('textbox', { name: 'What happens, and to whom?' }).fill('A captain loses command in a floating harbour.')
  await guide.getByRole('button', { name: 'Next / skip' }).click()
  await guide.getByRole('textbox', { name: 'What do they want to achieve?' }).fill('Recover the ship without harming the crew.')
  await guide.getByRole('button', { name: 'Develop from my answers' }).click()
  await expect(guide.getByTestId('writing-proposal')).toBeVisible()
  const draft = guide.getByRole('textbox', { name: 'Proposal: How do events cause one another?' })
  await draft.fill('My edited synopsis: she shares command.')
  await expect.poll(() => library.projects[story.id]?.writingGuide?.sections['story:root'].pending?.suggestions[0].value)
    .toBe('My edited synopsis: she shares command.')
  expect(calls).toHaveLength(1)
  expect((calls[0].values as Record<string, string>).goal).toBe('Recover the ship without harming the crew.')

  await page.reload()
  await openStory()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Close Ask to the Wizard', exact: true }).click()
  await guide.locator('summary').click()
  await expect(guide.getByRole('textbox', { name: 'Proposal: How do events cause one another?' })).toHaveValue('My edited synopsis: she shares command.')
  await guide.getByRole('button', { name: 'Apply selected changes' }).click()
  await expect.poll(() => library.projects[story.id]?.synopsis).toBe('My edited synopsis: she shares command.')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await closeApp(page, session)
})

test('Series coaching reaches setup, character, season, episode and scene without generating media', async ({ page }) => {
  const session = await gotoApp(page)
  const library = JSON.parse(readFileSync(new URL('../../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')) as SeriesLibrary
  let series = library.seriesById.series_signal
  await page.route('**/api/v1/series/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'PUT') series = { ...series, ...route.request().postDataJSON().series, revision: series.revision + 1 }
    await route.fulfill({ json: path.endsWith('/library') ? { ...library, seriesById: { [series.id]: series } }
      : path.endsWith('/recovery') ? { jobs: [] } : series })
  })
  await page.getByRole('tab', { name: 'Series Lab', exact: true }).click()
  await expect(page.getByTestId('writing-guide').filter({ hasText: 'Help me write · Series' })).toBeVisible()
  await expect(page.getByTestId('writing-guide').filter({ hasText: 'Help me write · Season' })).toBeVisible()
  await page.getByRole('button', { name: /^2 ·/ }).click()
  await page.getByRole('button', { name: 'Characters', exact: true }).click()
  const character = page.getByTestId('writing-guide').filter({ hasText: 'Help me write · Character' }).first()
  await character.locator('summary').click()
  await character.getByRole('textbox', { name: 'What does this character want?' }).fill('Save the harbour.')
  await expect.poll(() => series.characters[0].desire).toBe('Save the harbour.')
  await page.getByRole('button', { name: /^3 ·/ }).click()
  const episode = page.getByTestId('writing-guide').filter({ hasText: 'Help me write · Episode' })
  await expect(episode).toBeVisible()
  const scene = page.getByTestId('writing-guide').filter({ hasText: 'Help me write · Scene' }).first()
  await scene.locator('summary').click()
  await scene.getByRole('textbox', { name: 'Why does the story need this scene?' }).fill('Make the captain choose.')
  await expect.poll(() => Object.values(series.episodesById)[0].script[0].purpose).toBe('Make the captain choose.')
  await closeApp(page, session)
})
