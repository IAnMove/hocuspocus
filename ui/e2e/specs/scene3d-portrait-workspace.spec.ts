import { expect, test } from '@playwright/test'
import { applyScene3DTemplate } from '../../src/features/scene3d/templates'
import { gotoApp, closeApp } from '../helpers/gotoApp'

test('portrait preview fits, paused resizes repaint, and covered image objects remain editable', async ({ page }) => {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  const scene = applyScene3DTemplate('creative-ocean-window')
  await workspace.getByTestId('world3d-load-shot').setInputFiles({ name: 'portrait.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(scene)) })
  const list = workspace.getByTestId('scene3d-object-list')
  await expect(list.getByRole('button')).toHaveCount(scene.slots.length)
  // A rear image can be selected without raycasting through the foreground.
  await list.locator('[data-slot-id="background"]').click()
  await expect(list.locator('[data-slot-id="background"]')).toHaveAttribute('aria-pressed', 'true')
  const transforms = workspace.getByTestId('scene3d-transforms')
  await transforms.getByLabel('Position (m) X', { exact: true }).fill('0.25')
  await expect(transforms.getByLabel('Position (m) X', { exact: true })).toHaveValue('0.25')
  await workspace.getByRole('button', { name: '+ Larger', exact: true }).click()
  await workspace.getByRole('button', { name: '− Smaller', exact: true }).click()
  const picture = workspace.getByTestId('scene3d-preview-picture')
  const matte = workspace.getByTestId('scene3d-preview-matte')
  const canvas = picture.locator('canvas[data-engine]')
  const opaqueRatio = () => canvas.evaluate(node => {
    const source = node as HTMLCanvasElement
    const copy = document.createElement('canvas'); copy.width = 32; copy.height = 32
    const ctx = copy.getContext('2d')!; ctx.drawImage(source, 0, 0, 32, 32)
    const pixels = ctx.getImageData(0, 0, 32, 32).data
    let opaque = 0
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 250) opaque++
    return opaque / 1024
  })
  for (const width of [1440, 1000, 1600, 900]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(opaqueRatio).toBeGreaterThan(.95)
    const box = (await picture.boundingBox())!, outer = (await matte.boundingBox())!
    expect(box.height).toBeLessThan(530)
    expect(Math.abs(box.width / box.height - 9 / 16)).toBeLessThan(.01)
    expect(outer.width - box.width).toBeGreaterThan(20)
  }
  await workspace.getByRole('button', { name: 'Expand video', exact: true }).click()
  await expect(workspace.getByRole('button', { name: 'Exit fullscreen', exact: true })).toBeVisible()
  await expect.poll(opaqueRatio).toBeGreaterThan(.95)
  const full = (await picture.boundingBox())!, outer = (await matte.boundingBox())!
  expect(full.height).toBeGreaterThan(700)
  expect(Math.abs(full.width / full.height - 9 / 16)).toBeLessThan(.01)
  expect(outer.width - full.width).toBeGreaterThan(100)
  await workspace.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
  await expect.poll(opaqueRatio).toBeGreaterThan(.95)
  await expect(workspace.getByRole('button', { name: 'Expand video', exact: true })).toBeVisible()
  await closeApp(page, session)
})
