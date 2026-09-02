import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

test('opens extracted Story Lab Music, Trailer and Productions chrome', async ({ page }) => {
  const session = await gotoApp(page)

  const storyTab = page.getByRole('tab', { name: 'Story Lab' })
  await expect(storyTab).toBeVisible()
  await storyTab.click()

  const navigation = page.getByRole('navigation', { name: 'Story Lab sections' })
  await expect(navigation).toBeVisible()

  await navigation.getByRole('button', { name: 'Music' }).click()
  await expect(page.getByRole('heading', { name: 'Music bible' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate LLM suggestions' })).toBeVisible()

  await navigation.getByRole('button', { name: 'Productions' }).click()
  await expect(page.getByRole('heading', { name: 'Productions' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Comic adaptation' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Film adaptation' })).toBeVisible()

  await navigation.getByRole('button', { name: 'Trailer' }).click()
  await expect(page.getByRole('heading', { name: 'Cinematic trailer creator' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate complete trailer' })).toBeVisible()

  await closeApp(page, session)
})
