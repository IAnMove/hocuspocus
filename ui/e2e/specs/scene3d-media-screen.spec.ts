import { readFile, writeFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { gotoApp, closeApp } from '../helpers/gotoApp'
import { fulfillSeekable } from '../helpers/seekableMedia'
import { applyScene3DTemplate } from '../../src/features/scene3d/templates'

if (process.platform === 'win32') test.use({ channel: 'msedge' })
test.setTimeout(120_000)

test('a screen upload, dimensions and fit survive saving and reopening the shot', async ({ page }, testInfo) => {
  const session = await gotoApp(page)
  const url = '/api/v1/uploads/media-screen-test.png'
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64')
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { filename: 'media-screen-test.png', path: url, url, kind: 'image' } }))
  await page.route(`**${url}`, route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  await workspace.getByRole('button', { name: 'Add screen', exact: true }).click()
  const controls = workspace.getByTestId('scene3d-screen-controls').filter({ has: page.getByRole('button', { name: 'Remove screen', exact: true }) })
  await controls.getByTestId('asset-input-file').setInputFiles({ name: 'media-screen-test.png', mimeType: 'image/png', buffer: png })
  await expect(controls.getByText('media-screen-test.png', { exact: true })).toBeVisible()
  await controls.getByLabel('Content fit', { exact: true }).selectOption('cover')
  await controls.getByLabel('Screen style', { exact: true }).selectOption('billboard')
  await controls.getByLabel('Width / aspect', { exact: true }).fill('8')
  await controls.getByLabel('Height / aspect', { exact: true }).fill('4.5')
  const raw = await page.evaluate(() => JSON.stringify((window as Window & { __world3dDocument?: unknown }).__world3dDocument))
  expect(raw).toBeTruthy()
  const path = testInfo.outputPath('screen.world3d.json')
  await writeFile(path, raw)
  const document = JSON.parse(raw)
  const slot = document.slots.find((item: { media: string }) => item.media === 'screen')
  expect(slot.screen).toMatchObject({ sourceUrl: url, media: 'image', fit: 'cover', style: 'billboard', width: 8, height: 4.5 })
  expect(slot.screen.sourceRef).toMatchObject({ filename: 'media-screen-test.png', url })
  await controls.getByRole('button', { name: 'Remove screen', exact: true }).click()
  await expect(workspace.getByRole('button', { name: 'Remove screen', exact: true })).toHaveCount(0)
  await workspace.getByLabel('Open shot JSON').setInputFiles({ name: 'screen.world3d.json', mimeType: 'application/json', buffer: await readFile(path) })
  await expect(controls.getByLabel('Content fit', { exact: true })).toHaveValue('cover')
  await expect(controls.getByLabel('Screen style', { exact: true })).toHaveValue('billboard')
  await expect(controls.getByLabel('Width / aspect', { exact: true })).toHaveValue('8')
  await expect(controls.getByText('media-screen-test.png', { exact: true })).toBeVisible()
  await workspace.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(controls.getByLabel('Content fit', { exact: true })).toBeDisabled()
  await expect(workspace.getByRole('button', { name: 'Add screen', exact: true })).toBeDisabled()
  await closeApp(page, session)
})

test('a cutout background keeps its geometry and PSX look with seekable video through save and export', async ({ page }, testInfo) => {
  const session = await gotoApp(page)
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  const workspace = page.getByTestId('scene3d-workspace')
  const scene = applyScene3DTemplate('creative-ocean-window')
  scene.duration = 1
  // A fixed camera and a single background isolate media movement from camera/actors.
  scene.slots = scene.slots.filter(slot => slot.id === 'background')
  scene.camera.framing = undefined
  await workspace.getByLabel('Open shot JSON').setInputFiles({ name: 'ocean.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(scene)) })
  const controls = workspace.getByTestId('scene3d-screen-controls')
  await controls.getByLabel('Animate this layer').check()
  const url = '/api/v1/uploads/background-motion.webm'
  const video = await readFile(new URL('../../public/rig-previews/animation-jump.webm', import.meta.url))
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { filename: 'background-motion.webm', path: url, url, kind: 'video' } }))
  await page.route(`**${url}*`, fulfillSeekable(video, 'video/webm'))
  await controls.getByTestId('asset-input-file').setInputFiles({ name: 'background-motion.webm', mimeType: 'video/webm', buffer: video })
  await expect(controls.getByText('background-motion.webm', { exact: true })).toBeVisible()
  await expect(controls.getByLabel('Content fit', { exact: true })).toHaveValue('cover')
  const raw = await page.evaluate(() => JSON.stringify((window as Window & { __world3dDocument?: unknown }).__world3dDocument))
  expect(raw).toBeTruthy()
  const path = testInfo.outputPath('animated-background.world3d.json')
  await writeFile(path, raw)
  const document = JSON.parse(raw)
  const slot = document.slots[0]
  expect(slot).toMatchObject({ media: 'image', surface: 'cutout', position: scene.slots[0].position, scale: scene.slots[0].scale, imageLook: scene.slots[0].imageLook })
  expect(slot.screen).toMatchObject({ sourceUrl: url, media: 'video', fit: 'cover', loop: true })
  await controls.getByLabel('Animate this layer').uncheck()
  await workspace.getByLabel('Open shot JSON').setInputFiles({ name: 'animated-background.world3d.json', mimeType: 'application/json', buffer: await readFile(path) })
  await expect(controls.getByLabel('Animate this layer')).toBeChecked()
  await expect(controls.getByText('background-motion.webm', { exact: true })).toBeVisible()
  // Playwright Chromium (Chrome for Testing) supports H.264, so Linux would
  // encode this WebM cutout and miss seeked. Native MP4 stays on Windows Edge.
  const canEncode = process.platform === 'win32' && await page.evaluate(async () => {
    if (typeof VideoEncoder === 'undefined') return false
    const result = await VideoEncoder.isConfigSupported({ codec: 'avc1.640028', width: 1280, height: 720, bitrate: 5_000_000, framerate: 30, avc: { format: 'avc' } })
    return Boolean(result.supported)
  })
  if (!canEncode) {
    await closeApp(page, session)
    return
  }
  await page.route('**/api/v1/scenes/recordings', route => route.fulfill({ json: { name: 'animated-background.mp4', type: 'video', url: '/api/v1/file/animated-background.mp4' } }))
  await workspace.getByTestId('world3d-export').click()
  await expect(workspace.getByTestId('world3d-export-note')).toContainText('animated-background.mp4', { timeout: 90_000 })
  const difference = await page.evaluate(async () => {
    const blob = (window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4!
    const url = URL.createObjectURL(blob), video = document.createElement('video')
    const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32
    const ctx = canvas.getContext('2d')!
    const wait = (event: 'loadeddata' | 'seeked', ms: number) => new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer); video.removeEventListener(event, done); video.removeEventListener('error', failed)
        if (error) reject(error); else resolve()
      }
      const done = () => finish(), failed = () => finish(new Error('Background export cannot be decoded'))
      const timer = setTimeout(() => event === 'seeked' ? finish() : finish(new Error('Background export did not load')), ms)
      video.addEventListener(event, done, { once: true }); video.addEventListener('error', failed, { once: true })
    })
    try {
      const loaded = wait('loadeddata', 8_000); video.src = url; await loaded
      const sample = async (seconds: number) => {
        const sought = wait('seeked', 500); video.currentTime = seconds; await sought
        ctx.drawImage(video, 0, 0, 32, 32); return ctx.getImageData(0, 0, 32, 32).data
      }
      const first = await sample(.05), last = await sample(.8)
      return first.reduce((sum, value, index) => sum + Math.abs(value - last[index]), 0) / first.length
    } finally { video.removeAttribute('src'); video.load(); URL.revokeObjectURL(url) }
  })
  expect(difference).toBeGreaterThan(1)
  await closeApp(page, session)
})
