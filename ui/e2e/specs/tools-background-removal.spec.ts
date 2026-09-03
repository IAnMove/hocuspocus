import { expect, test, type Request } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

async function openBackgroundRemovalTools(page: Parameters<typeof gotoApp>[0]) {
  await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
  await page.getByRole('tab', { name: 'Tools', exact: true }).click()
  await page.getByRole('button', { name: 'Remove background', exact: true }).click()
  const picker = page.getByRole('combobox', { name: 'Source Image', exact: true })
  await expect(picker).toBeVisible()
  await expect(picker.locator('option[value="asset-hero"]')).toHaveCount(1)
  return picker
}

function collectRequests(page: Parameters<typeof gotoApp>[0], pathname: string): Request[] {
  const requests: Request[] = []
  page.on('request', request => {
    if (new URL(request.url()).pathname === pathname) requests.push(request)
  })
  return requests
}

test('runs Remove Background from direct Tools and exposes the derived asset', async ({ page }) => {
  const session = await gotoApp(page)
  const submissions = collectRequests(page, '/api/v1/tools/remove-background')
  const statuses = collectRequests(page, '/api/v1/status/tool-bg-e2e')

  try {
    const picker = await openBackgroundRemovalTools(page)
    const run = page.getByRole('button', { name: 'Remove Background', exact: true })
    await expect(run).toBeDisabled()
    await expect(page.getByRole('status')).toContainText('Choose an image from the library')

    await picker.selectOption('asset-hero')
    await expect(page.getByRole('img', { name: 'hero.png', exact: true })).toBeVisible()
    await expect(run).toBeEnabled()

    await run.click()
    await expect.poll(() => submissions.length).toBe(1)
    const payload = JSON.parse(submissions[0].postData() || '{}') as Record<string, unknown>
    expect(payload).toMatchObject({
      asset_id: 'asset-hero',
      source: 'hero.png',
      source_workspace: 'default',
      workspace: 'default',
    })
    await expect(page.getByText('Queued...', { exact: true })).toBeVisible()
    await expect.poll(() => statuses.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(2)

    await page.getByRole('button', { name: 'Media', exact: true }).click()
    await page.getByRole('tab', { name: 'Assets', exact: true }).click()
    const cutout = page.locator('article').filter({ hasText: 'hero-no-background.png' })
    await expect(cutout).toBeVisible()
    await expect(cutout.locator('img')).toHaveCount(1)

    await cutout.getByRole('button', { name: 'Extra info', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Extra info' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('remove_background')
    await expect(dialog).toContainText('rembg-u2net')
    await expect(dialog).toContainText('asset-hero')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()

    // The derived asset is a normal catalog item: it can be selected again as
    // an exact source without going through Wizard or a second upload.
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await page.getByRole('tab', { name: 'Tools', exact: true }).click()
    await page.getByRole('button', { name: 'Remove background', exact: true }).click()
    await page.getByRole('button', { name: 'Clear', exact: true }).click()
    const reusablePicker = page.getByRole('combobox', { name: 'Source Image', exact: true })
    await expect(reusablePicker.locator('option[value="asset-hero-cutout"]')).toHaveCount(1)
    await reusablePicker.selectOption('asset-hero-cutout')
    await expect(page.locator('aside').getByRole('img', { name: 'hero-no-background.png', exact: true })).toBeVisible()
  } finally {
    await closeApp(page, session)
  }
})

test('shows progress and lets the user cancel a Remove Background run', async ({ page }) => {
  const session = await gotoApp(page, { backgroundRemovalMode: 'cancel' })
  const cancellations = collectRequests(page, '/api/v1/cancel/tool-bg-e2e')

  try {
    const picker = await openBackgroundRemovalTools(page)
    await picker.selectOption('asset-hero')
    await page.getByRole('button', { name: 'Remove Background', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible({ timeout: 7_000 })

    await page.getByRole('button', { name: 'Stop', exact: true }).click()
    await expect.poll(() => cancellations.length).toBe(1)
    await expect(page.getByText('Cancelled', { exact: true })).toBeVisible({ timeout: 7_000 })
  } finally {
    await closeApp(page, session)
  }
})

test('keeps a tool failure visible in the activity card', async ({ page }) => {
  const session = await gotoApp(page, { backgroundRemovalMode: 'fail' })

  try {
    const picker = await openBackgroundRemovalTools(page)
    await picker.selectOption('asset-hero')
    await page.getByRole('button', { name: 'Remove Background', exact: true }).click()
    await expect(page.getByText('Generation Failed', { exact: true })).toBeVisible({ timeout: 7_000 })
    await expect(page.getByText('rembg test failure', { exact: true })).toBeVisible()
  } finally {
    await closeApp(page, session)
  }
})
