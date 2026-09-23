import { expect, test } from '@playwright/test'
import { gotoApp, closeApp } from '../helpers/gotoApp'

// Real Three.js editor against the closed, simulated API.
test('pixel worlds: a TV wall template relights, adds TVs and shares one recording', async ({ page }, testInfo) => {
  // Two dozen video screens under software WebGL are slow on CI runners.
  test.slow()
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  await workspace.locator('summary', { hasText: 'Shot library' }).click()
  await workspace.getByRole('button', { name: 'Pixel worlds', exact: true }).click()
  for (const id of ['pixel-tv-wall', 'pixel-moon-lake', 'pixel-tv-lake', 'pixel-aurora-peaks']) {
    await expect(workspace.getByTestId(`world3d-template-${id}`)).toBeVisible()
  }
  await workspace.getByTestId('world3d-template-pixel-tv-wall').click()
  const panel = workspace.getByTestId('pixel-world-controls')
  await expect(panel.getByRole('checkbox', { name: 'Pixel world lighting' })).toBeChecked()
  await expect(panel.getByRole('combobox', { name: 'World' })).toHaveValue('pixel-gallery')
  const count = panel.getByText(/^\d+ TVs$/)
  const before = Number((await count.textContent())!.split(' ')[0])
  expect(before).toBeGreaterThanOrEqual(20)
  await panel.getByRole('button', { name: 'Add TV' }).click()
  await expect(count).toHaveText(`${before + 1} TVs`)
  // A lighting program is a list of moods; add one and remove it again.
  await panel.getByRole('combobox', { name: 'Add mood' }).selectOption('aurora')
  await expect(panel.getByRole('button', { name: 'Remove Aurora' })).toBeVisible()
  await panel.getByRole('button', { name: 'Remove Aurora' }).click()
  await expect(panel.getByRole('button', { name: 'Remove Aurora' })).toHaveCount(0)
  await page.waitForTimeout(1500)
  await testInfo.attach('tv-wall', { body: await workspace.locator('canvas').first().screenshot(), contentType: 'image/png' })
  expect(errors).toEqual([])
  await closeApp(page, session)
})
