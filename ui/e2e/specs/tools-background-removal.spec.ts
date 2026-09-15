import { expect, test, type Request } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

async function chooseLibraryFile(page: Parameters<typeof gotoApp>[0], filename: string) {
  await page.getByRole('button', { name: 'From HocusPocus' }).click()
  const explorer = page.getByRole('dialog').filter({ has: page.getByTestId('asset-explorer') })
  await expect(explorer).toBeVisible()
  await explorer.locator('button[title="' + filename + '"]').click()
  await explorer.getByRole('button', { name: 'Choose', exact: true }).click()
}

async function openBackgroundRemovalTools(page: Parameters<typeof gotoApp>[0]) {
  await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
  await page.getByRole('tab', { name: 'Tools', exact: true }).click()
  await page.getByRole('button', { name: 'Remove background', exact: true }).click()
  await expect(page.getByRole('button', { name: 'From HocusPocus' })).toBeVisible()
}

async function openUpscaleTools(page: Parameters<typeof gotoApp>[0]) {
  await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
  await page.getByRole('tab', { name: 'Tools', exact: true }).click()
  await page.getByRole('button', { name: 'Upscale', exact: true }).click()
  await expect(page.getByRole('button', { name: 'From HocusPocus' })).toBeVisible()
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
    await openBackgroundRemovalTools(page)
    const run = page.getByRole('button', { name: 'Remove Background', exact: true })
    await expect(run).toBeDisabled()
    await expect(page.getByRole('status')).toContainText('Choose an image from the library')

    await chooseLibraryFile(page, 'hero.png')
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
    // The activity footer, job placeholder and progress card can all expose
    // the same status while a tool job is queued. Assert the first visible
    // status instead of requiring a globally unique text node.
    await expect(page.getByText('Queued...', { exact: true }).first()).toBeVisible()
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
    await chooseLibraryFile(page, 'hero-no-background.png')
    await expect(page.getByTestId('direct-generation-workspace').getByRole('img', { name: 'hero-no-background.png', exact: true })).toBeVisible()
  } finally {
    await closeApp(page, session)
  }
})

test('shows progress and lets the user cancel a Remove Background run', async ({ page }) => {
  const session = await gotoApp(page, { backgroundRemovalMode: 'cancel' })
  const cancellations = collectRequests(page, '/api/v1/cancel/tool-bg-e2e')

  try {
    await openBackgroundRemovalTools(page)
    await chooseLibraryFile(page, 'hero.png')
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
    await openBackgroundRemovalTools(page)
    await chooseLibraryFile(page, 'hero.png')
    await page.getByRole('button', { name: 'Remove Background', exact: true }).click()
    await expect(page.getByText('Generation Failed', { exact: true })).toBeVisible({ timeout: 7_000 })
    await expect(page.getByText('rembg test failure', { exact: true })).toBeVisible()
  } finally {
    await closeApp(page, session)
  }
})

test('runs the shared Upscale action from an image and publishes a derived asset', async ({ page }) => {
  const session = await gotoApp(page, { upscaleMode: 'complete' })
  const submissions = collectRequests(page, '/api/v1/generation/commands')
  const legacySubmissions = collectRequests(page, '/api/v1/tools/upscale')
  const statuses = collectRequests(page, '/api/v1/status/tool-upscale-e2e')

  try {
    await openUpscaleTools(page)
    const run = page.getByRole('button', { name: 'Upscale Clip', exact: true })
    await expect(run).toBeDisabled()

    await chooseLibraryFile(page, 'hero.png')
    await expect(page.getByRole('img', { name: 'hero.png', exact: true })).toBeVisible()
    const imageRun = page.getByRole('button', { name: 'Upscale Image', exact: true })
    await expect(imageRun).toBeEnabled()
    const acknowledgement = page.waitForResponse(response => (
      new URL(response.url()).pathname === '/api/v1/generation/commands'
      && response.request().method() === 'POST'
    ))
    await imageRun.click()

    await expect.poll(() => submissions.length).toBe(1)
    const payload = JSON.parse(submissions[0].postData() || '{}') as Record<string, unknown>
    expect(payload).toMatchObject({
      version: 2,
      operation: 'tools.upscale',
      intent_id: expect.any(String),
    })
    const input = payload.input as Record<string, unknown>
    const params = input.params as Record<string, unknown>
    expect(input).toMatchObject({ workspace: 'default' })
    expect(params).toMatchObject({
      source: 'asset-hero',
      source_kind: 'image',
      source_workspace: 'default',
    })
    expect(payload.asset_id).toBeUndefined()
    expect(payload.source).toBeUndefined()
    expect(payload.video_path).toBeUndefined()
    const response = await acknowledgement
    expect(response.status()).toBe(200)
    const envelope = await response.json() as Record<string, unknown>
    expect(envelope.replayed).toBe(false)
    expect(envelope.receipt).toMatchObject({
      version: 1,
      commandId: payload.intent_id,
      operation: 'tools.upscale',
      status: 'queued',
      taskIds: ['task-generation-tool-upscale-e2e'],
      result: {
        job_id: 'tool-upscale-e2e',
        task_id: 'task-generation-tool-upscale-e2e',
        workspace: 'default',
        status: 'queued',
      },
      commandVersion: 2,
      fingerprintVersion: 2,
      contentFingerprint: expect.stringMatching(/^[a-f0-9]{64}$/),
    })
    expect(legacySubmissions).toHaveLength(0)
    await expect(page.getByText('Queued...', { exact: true }).first()).toBeVisible()
    await expect.poll(() => statuses.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(2)

    await page.getByRole('button', { name: 'Media', exact: true }).click()
    await page.getByRole('tab', { name: 'Assets', exact: true }).click()
    const upscaled = page.locator('article').filter({ hasText: 'hero_upscaled.png' })
    await expect(upscaled).toBeVisible()
    await upscaled.getByRole('button', { name: 'Extra info', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Extra info' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('upscale')
    await expect(dialog).toContainText('asset-hero')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  } finally {
    await closeApp(page, session)
  }
})
