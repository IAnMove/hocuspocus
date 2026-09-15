import { expect, test } from '@playwright/test'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from '../../src/features/scene3d/camera'
import { applyScene3DTemplate } from '../../src/features/scene3d/templates'
import { gotoApp, closeApp } from '../helpers/gotoApp'

// The real Three.js scene runs against a closed, simulated API. No model provider.
test('3D templates, playback speed and object transforms work in the editor', async ({ page }, testInfo) => {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  await expect(workspace).toBeVisible()
  const play = workspace.getByRole('button', { name: 'Play', exact: true })
  await expect(play).toBeVisible()
  const bounds = await play.boundingBox()
  expect(bounds?.height).toBeGreaterThanOrEqual(44)
  expect(bounds?.width).toBeGreaterThanOrEqual(140)

  await workspace.getByRole('combobox', { name: 'Speed', exact: true }).selectOption('2')
  await expect(workspace.getByText('Output: 3.00 s')).toBeVisible()
  await play.click()
  await expect(workspace.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  await expect(workspace.getByLabel('Size', { exact: true })).toBeDisabled()
  await workspace.getByRole('button', { name: 'Pause', exact: true }).click()
  await workspace.getByRole('button', { name: 'Back to start' }).click()
  await expect(workspace.getByRole('slider', { name: 'Scene position' })).toHaveValue('0')

  await workspace.getByRole('button', { name: '+ Larger', exact: true }).click()
  await expect(workspace.getByLabel('Size', { exact: true })).toHaveValue('1.25')
  await workspace.getByLabel('Position (m) X', { exact: true }).fill('1.2')
  await workspace.getByLabel('Position (m) Y', { exact: true }).fill('0.5')
  await workspace.getByLabel('Position (m) Z', { exact: true }).fill('-0.8')
  await workspace.getByLabel('Rotation Y (°)', { exact: true }).fill('45')
  await workspace.getByRole('button', { name: 'Reset transform' }).click()
  await expect(workspace.getByLabel('Position (m) X', { exact: true })).toHaveValue('-0.95')

  // Drag the real X handle in the WebGL viewport, then verify the document field.
  const scene = applyScene3DTemplate('two-shot')
  const viewport = workspace.getByRole('region', { name: '3D scene', exact: true })
  const canvas = viewport.locator('canvas[data-engine]')
  await viewport.focus()
  await page.keyboard.press('r')
  await expect(workspace.getByRole('button', { name: 'Rotate Y', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(workspace.getByTestId('scene3d-transform-help')).toContainText('R to rotate')
  await page.keyboard.press('g')
  await expect(workspace.getByRole('button', { name: 'Move', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await canvas.scrollIntoViewIfNeeded()
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  const eye = cameraEyeAtTime(scene.camera, 0, scene.duration, scene.slots)
  const look = cameraLookAtTime(scene.camera, 0, scene.duration, scene.slots)
  const origin = scene.slots[0].position
  const distance = Math.hypot(...origin.map((value, i) => value - eye[i]))
  const handleScale = distance * Math.min(1.9 * Math.tan(Math.PI * scene.camera.fov / 360), 7) * 0.85 / 4
  const point = projectPoint([origin[0] + handleScale * 0.4, origin[1], origin[2]], eye, look, scene.camera.fov, box!.width / box!.height)!
  const x = box!.x + point.x * box!.width
  const y = box!.y + point.y * box!.height
  await page.mouse.move(x, y)
  await page.mouse.down()
  await expect(workspace.getByTestId('scene3d-transform-help')).toBeVisible()
  await page.mouse.move(x + 65, y, { steps: 10 })
  await page.mouse.up()
  await expect(workspace.getByTestId('scene3d-transform-help')).toHaveCount(0)
  await expect(workspace.getByLabel('Position (m) X', { exact: true })).not.toHaveValue('-0.95')
  await workspace.getByRole('button', { name: 'Reset transform' }).click()

  // R changes the real ring gizmo; dragging it must persist a new yaw.
  const initialYaw = await workspace.getByLabel('Rotation Y (°)', { exact: true }).inputValue()
  await viewport.focus()
  await page.keyboard.press('r')
  await canvas.scrollIntoViewIfNeeded()
  const rotateBox = (await canvas.boundingBox())!
  const ring = projectPoint([origin[0] + handleScale * 0.5, origin[1], origin[2]], eye, look, scene.camera.fov, rotateBox.width / rotateBox.height)!
  const ringX = rotateBox.x + ring.x * rotateBox.width
  const ringY = rotateBox.y + ring.y * rotateBox.height
  await page.mouse.move(ringX, ringY)
  await page.mouse.down()
  await page.screenshot({ path: testInfo.outputPath('video3d-rotation-help.png'), fullPage: true })
  await page.mouse.move(ringX + 45, ringY - 25, { steps: 10 })
  await page.mouse.up()
  await expect(workspace.getByLabel('Rotation Y (°)', { exact: true })).not.toHaveValue(initialYaw)
  await workspace.getByRole('button', { name: 'Reset transform' }).click()

  await workspace.getByLabel('Rotation Y (°)', { exact: true }).fill('0')
  await viewport.focus()
  await page.keyboard.press('s')
  await expect(workspace.getByRole('button', { name: 'Scale', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await canvas.scrollIntoViewIfNeeded()
  const scaleBox = (await canvas.boundingBox())!
  const scaleX = scaleBox.x + point.x * scaleBox.width
  const scaleY = scaleBox.y + point.y * scaleBox.height
  await page.mouse.move(scaleX, scaleY)
  await page.mouse.down()
  await page.mouse.move(scaleX + 40, scaleY, { steps: 10 })
  await page.mouse.up()
  await expect(workspace.getByLabel('Size', { exact: true })).not.toHaveValue('1')
  await workspace.getByRole('button', { name: 'Reset transform' }).click()
  // Typing outside the viewport does not change its mode.
  await workspace.getByLabel('Size', { exact: true }).focus()
  await page.keyboard.press('r')
  await expect(workspace.getByRole('button', { name: 'Scale', exact: true })).toHaveAttribute('aria-pressed', 'true')

  await workspace.locator('summary').filter({ hasText: 'Shot library' }).click()
  await workspace.getByRole('searchbox', { name: 'Search templates' }).fill('close')
  await workspace.getByTestId('world3d-template-face-closeup').click()
  await workspace.locator('summary').filter({ hasText: 'Shot library' }).click()
  const framing = workspace.locator('details').filter({ has: page.locator('summary', { hasText: 'Subject framing' }) })
  await framing.locator('summary').click()
  await expect(framing.getByRole('checkbox', { name: 'Subject framing', exact: true })).toBeChecked()
  await framing.getByRole('combobox', { name: 'Point of interest', exact: true }).selectOption('center')
  await framing.getByRole('spinbutton', { name: 'Camera at end Z', exact: true }).fill('2.4')
  await expect(framing.getByRole('spinbutton', { name: 'Camera at end Z', exact: true })).toHaveValue('2.4')
  await play.click()
  await expect(framing.getByRole('combobox', { name: 'Point of interest', exact: true })).toBeDisabled()
  await workspace.getByRole('button', { name: 'Pause', exact: true }).click()
  await workspace.getByRole('button', { name: 'Back to start', exact: true }).click()
  await expect(workspace.getByRole('slider', { name: 'Scene position' })).toHaveValue('0')
  await expect(workspace.getByRole('combobox', { name: 'Speed', exact: true })).toHaveValue('2')
  await workspace.getByRole('button', { name: 'Scale', exact: true }).click()
  await expect(workspace.getByRole('button', { name: 'Scale', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await workspace.getByRole('button', { name: 'Move', exact: true }).click()
  await page.getByTestId('world3d-editor').evaluate(element => { element.scrollTop = 0 })
  await page.screenshot({ path: testInfo.outputPath('video3d-editor-desktop.png'), fullPage: true })

  // Mobile controls must remain reachable without horizontal page overflow.
  await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Expand editor', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  await expect(play).toBeVisible()
  await workspace.getByRole('button', { name: 'Scale', exact: true }).click()
  await expect(workspace.getByLabel('Size', { exact: true })).toBeVisible()
  const overflow = await workspace.evaluate(element => element.scrollWidth - element.clientWidth)
  expect(overflow).toBeLessThanOrEqual(2)
  await page.getByTestId('world3d-editor').evaluate(element => { element.scrollTop = 0 })
  await page.screenshot({ path: testInfo.outputPath('video3d-editor-mobile.png'), fullPage: true })
  await closeApp(page, session)
})

test('speed is baked into a decodable MP4 and its scene metadata', async ({ page }) => {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  const available = await page.evaluate(async () => {
    if (typeof VideoEncoder === 'undefined') return false
    const result = await VideoEncoder.isConfigSupported({ codec: 'avc1.640028', width: 1280, height: 720, bitrate: 5_000_000, framerate: 30, avc: { format: 'avc' } })
    return result.supported
  })
  test.skip(!available, 'This Chromium does not provide an H.264 encoder')
  let metadata: { scene: { duration: number }; recipe: { document: { playbackSpeed: number } } } | undefined
  await page.route('**/api/v1/scenes/recordings', async route => {
    const payload = route.request().postDataBuffer()!.toString('utf8')
    const field = payload.split('name="metadata"\r\n\r\n')[1].split('\r\n--')[0]
    metadata = JSON.parse(field)
    await route.fulfill({ json: { name: 'speed-check.mp4', type: 'video', url: '/api/v1/file/speed-check.mp4' } })
  })
  const workspace = page.getByTestId('scene3d-workspace')
  await workspace.getByRole('combobox', { name: 'Speed', exact: true }).selectOption('4')
  await workspace.getByTestId('world3d-export').click()
  await expect(workspace.getByRole('button', { name: 'Play', exact: true })).toBeDisabled()
  await expect(workspace.getByTestId('world3d-export-note')).toContainText('speed-check.mp4', { timeout: 25_000 })
  expect(metadata?.scene.duration).toBe(1.5)
  expect(metadata?.recipe.document.playbackSpeed).toBe(4)
  const decoded = await page.evaluate(async () => {
    const blob = (window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4!
    const url = URL.createObjectURL(blob)
    const video = document.createElement('video')
    try {
      return await new Promise<{ duration: number; width: number; height: number }>((resolve, reject) => {
        video.onloadedmetadata = () => resolve({ duration: video.duration, width: video.videoWidth, height: video.videoHeight })
        video.onerror = () => reject(new Error('Exported MP4 cannot be decoded'))
        video.src = url
      })
    } finally { video.removeAttribute('src'); video.load(); URL.revokeObjectURL(url) }
  })
  expect(decoded.duration).toBeCloseTo(1.5, 1)
  expect(decoded.width).toBe(1280)
  expect(decoded.height).toBe(720)
  await closeApp(page, session)
})
