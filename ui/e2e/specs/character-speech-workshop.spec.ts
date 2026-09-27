import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createCharacterKit, type CharacterKitLibrary } from '../../src/lib/characterKit'

test('Character Creator opens the manual speech workshop and saves reviewed drafts without inference', async ({ page }) => {
  const session = await gotoApp(page)
  const kit = createCharacterKit('Speech test fixture')
  kit.base = { id: 'speech-base', name: 'Base', source: '/speech-fixture.svg', kind: 'image', alphaStatus: 'opaque', reviewState: 'pending' }
  let library: CharacterKitLibrary = { version: 1, revision: 7, activeId: kit.id, kits: { [kit.id]: kit } }
  const mutations: string[] = []
  const inference: string[] = []
  let loads = 0
  page.on('request', request => {
    if (request.method() !== 'GET' && /\/(generate|generation|analyze|cleanup|remove-background|describe-refs)(\b|\/)/.test(new URL(request.url()).pathname)) inference.push(request.url())
  })
  await page.route('**/speech-fixture.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#8a908f"/></svg>' }))
  await page.route('**/api/v1/character-kits/library**', async route => {
    const request = route.request()
    if (request.method() === 'GET') {
      loads += 1
      expect(new URL(request.url()).searchParams.get('workspace')).toBe('default')
    } else {
      expect(request.method()).toBe('PATCH')
      const body = request.postDataJSON()
      expect(body.workspace).toBe('default')
      expect(body.baseRevision).toBe(library.revision)
      expect(body.kit.base.reviewState).toBe('approved')
      mutations.push(request.url())
      library = { ...library, revision: library.revision + 1, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(library) })
  })
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  expect(loads).toBe(0)
  const drawer = page.locator('summary').filter({ hasText: 'Prepare 2D speech' })
  await drawer.click()
  const workshop = page.getByRole('region', { name: 'Prepare 2D speech', exact: true })
  await expect(workshop).toBeVisible()
  await expect(workshop.getByRole('combobox', { name: 'Saved character' })).toHaveValue(kit.id)
  await expect(workshop.getByText(/Nothing is generated until you request it/)).toBeVisible()
  await expect(workshop.getByRole('button', { name: 'Generate / replace Open', exact: true })).toBeDisabled()
  await expect(workshop.getByRole('button', { name: 'Blink', exact: true })).toBeHidden()
  await workshop.getByRole('button', { name: 'Use pack', exact: true }).click()
  await workshop.getByRole('button', { name: 'Play included voice sample' }).click()
  const audio = workshop.locator('audio[src="/speech-examples/english-preview.mp3"]')
  await expect.poll(() => audio.evaluate(element => (element as HTMLAudioElement).currentTime)).toBeGreaterThan(.3)
  await workshop.getByRole('button', { name: 'Stop sample', exact: true }).click()
  await expect.poll(() => audio.evaluate(element => (element as HTMLAudioElement).paused)).toBe(true)
  await workshop.getByRole('button', { name: 'I have reviewed this base image' }).click()
  await expect(workshop.getByText(/Unsaved changes/)).toBeVisible()
  await drawer.click()
  await drawer.click()
  await expect(workshop.getByText(/Unsaved changes/)).toBeVisible()
  await page.getByRole('tab', { name: 'Story Lab', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'Story Lab sections' })).toBeVisible()
  await expect(workshop).toHaveCount(0)
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  await drawer.click()
  await expect(workshop.getByText(/Unsaved changes/)).toBeVisible()
  await workshop.getByRole('button', { name: 'Save speech character' }).click()
  await expect(workshop.getByText(/Character saved to this workspace/)).toBeVisible()
  expect(mutations).toHaveLength(1)
  expect(inference).toEqual([])
  await workshop.getByRole('button', { name: 'Reload library', exact: true }).click()
  await expect(workshop.getByRole('button', { name: 'I have reviewed this base image' })).toBeDisabled()
  await expect(workshop.getByRole('button', { name: 'Save speech character' })).toBeDisabled()
  expect(loads).toBe(3)
  await closeApp(page, session)
})
