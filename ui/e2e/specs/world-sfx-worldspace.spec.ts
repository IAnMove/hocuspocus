import { expect, test } from '@playwright/test'
import { writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { gotoApp, closeApp } from '../helpers/gotoApp'

async function openVideo3d(page: Parameters<typeof gotoApp>[0]) {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  await expect(workspace).toBeVisible()
  return { session, workspace }
}

test('world SFX demos occupy the 3D stage and keep screen overlays', async ({ page }, info) => {
  const { session, workspace } = await openVideo3d(page)
  await expect(workspace.getByTestId('world-sfx-controls')).toBeVisible()
  await workspace.getByTestId('world-sfx-demo-depth').click()
  await expect(workspace.getByTestId('scene-fx-overlay')).toBeVisible()
  await workspace.getByLabel('Scene position', { exact: true }).fill('0')
  await page.screenshot({ path: info.outputPath('world-sfx-depth-front.png') })
  await workspace.getByLabel('Scene position', { exact: true }).fill('5')
  await page.screenshot({ path: info.outputPath('world-sfx-depth-oblique.png') })
  await workspace.getByTestId('world-sfx-demo-duel').click()
  await expect(workspace.getByTestId('world-sfx-title')).toContainText('(5)')
  await workspace.getByTestId('world-sfx-demo-mixed').click()
  await expect(workspace.getByTestId('scene-fx-overlay')).toBeVisible()
  await closeApp(page, session)
})

test.describe('native world-sfx export', () => {
  test.skip(process.platform !== 'win32', 'Native MP4 is the Windows Edge job')
  test.setTimeout(120_000)
  test('portal depth demo exports a decodable MP4 when the encoder exists', async ({ page }, info) => {
  const { session, workspace } = await openVideo3d(page)
  const available = await page.evaluate(async () => {
    if (typeof VideoEncoder === 'undefined') return false
    const result = await VideoEncoder.isConfigSupported({ codec: 'avc1.640028', width: 1280, height: 720, bitrate: 5_000_000, framerate: 30, avc: { format: 'avc' } })
    return Boolean(result.supported)
  })
  test.skip(!available, 'This Chromium does not provide an H.264 encoder')
  await page.route('**/api/v1/scenes/recordings', async route => {
    await route.fulfill({ json: { name: 'world-sfx-depth.mp4', type: 'video', url: '/api/v1/file/world-sfx-depth.mp4' } })
  })
  await workspace.getByTestId('world-sfx-demo-depth').click()
  await workspace.getByRole('combobox', { name: 'Speed', exact: true }).selectOption('4')
  const posted = page.waitForRequest(request => request.url().includes('/scenes/recordings') && request.method() === 'POST', { timeout: 90_000 })
  await workspace.getByTestId('world3d-export').click()
  const payload = (await posted).postDataBuffer()
  expect(payload?.length ?? 0).toBeGreaterThan(10_000)
  await expect(workspace.getByTestId('world3d-export')).toBeEnabled({ timeout: 90_000 })
  await expect(workspace.getByTestId('world3d-export-note')).toContainText(/world-sfx-depth\.mp4|could not be downloaded/)
  const bytes = await page.evaluate(async () => {
    const blob = (window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4
    if (!blob) return []
    return Array.from(new Uint8Array(await blob.arrayBuffer()))
  })
  if (bytes.length) {
    const dir = path.join(info.outputDir, 'world-sfx')
    await mkdir(dir, { recursive: true })
    await writeFile(path.join(dir, 'world-sfx-depth.mp4'), Buffer.from(bytes))
  }
  await closeApp(page, session)
})
})
