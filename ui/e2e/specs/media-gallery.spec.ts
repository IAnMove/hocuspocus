import { readFile } from 'node:fs/promises'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { fulfillSeekable } from '../helpers/seekableMedia'
import type { ApiOutput } from '../../src/api/outputs'
import type { OutputMetadata } from '../../src/types'
import { closeApp } from '../helpers/gotoApp'
import { installApiRoutes } from '../helpers/apiRoutes'
import { lockUiLanguage } from '../helpers/lockUiLanguage'
import { bootWatchdogPlaceholderPath } from '../helpers/bootWatchdogPlaceholderPath'

const LONG_PROMPT = `Literal prompt: a portrait beneath a blue sky. ${'Keep every detail and preserve the original wording. '.repeat(100)}END OF LITERAL PROMPT`
const FIXTURES: ApiOutput[] = Array.from({ length: 54 }, (_, index) => {
  const type = index % 7 === 2 ? 'video' : 'image'
  const name = `gallery-${String(index).padStart(3, '0')}.${type === 'video' ? 'mp4' : 'png'}`
  return {
    name, type, mode: type, favorite: false, size: 2_097_152,
    created_at: 1_790_000_000 - index, completed_at: 1_790_000_020 - index,
    completion_time_source: 'metadata', url: `/api/v1/file/${name}?workspace=default`,
    thumbnail_url: `/api/v1/outputs/thumbnail/${name}?workspace=default`,
  }
})
const FIRST_IMAGE = FIXTURES[0].name
const LAST_IMAGE = FIXTURES.at(-1)!.name
const VIDEO = FIXTURES[2].name

function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}
function svg(name: string) {
  const portrait = Number(name.match(/gallery-(\d+)/)?.[1] || 0) % 2 === 0
  const width = portrait ? 480 : 1600, height = portrait ? 1600 : 480
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="${portrait ? '#244573' : '#744260'}"/><circle cx="${width / 2}" cy="${height / 2}" r="150" fill="#e6c85d"/><text x="20" y="50" fill="white" font-size="30">${name}</text></svg>`
}
function metadata(name: string): OutputMetadata {
  return {
    source: 'sidecar', job_id: `job-${name}`, task_id: `task-${name}`,
    created_at: 1_790_000_000, completed_at: 1_790_000_020, generation_time: 20,
    params: { model_type: 'fixture-portrait-model', resolution: '480x1600', seed: 123456,
      num_inference_steps: 18, guidance_scale: 3.5, prompt: LONG_PROMPT,
      negative_prompt: 'Do not crop the portrait', saved_fixture_identity: name },
  }
}
async function bootGalleryApp(page: Page, beforeGoto?: () => Promise<void>) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const session = await installApiRoutes(page)
  // In Vite DEV, symlinked module URLs contain /api/ in their filesystem path;
  // only real HTTP API requests should be served by the simulated API helper.
  await page.route(url => url.pathname.startsWith('/@fs/') || url.pathname.startsWith('/src/'), route => route.continue())
  await lockUiLanguage(page, 'en')
  await page.addInitScript(() => localStorage.setItem('hocuspocus-wizard-sidebar-collapsed', 'true'))
  await page.addInitScript({ path: bootWatchdogPlaceholderPath })
  await beforeGoto?.()
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Studios', exact: true })).toBeVisible({ timeout: 30_000 })
  const closeWizard = page.getByRole('button', { name: 'Close Ask to the Wizard', exact: true })
  if (await closeWizard.isVisible()) await closeWizard.click()
  return session
}

async function installGalleryFixtures(page: Page) {
  const imageGate = gate()
  let metadataGate = gate(), metadataReplies = 0
  const requests: string[] = []
  await page.route('**/api/v1/outputs?*', async route => {
    const url = new URL(route.request().url()), kind = url.searchParams.get('media_type')
    const outputs = kind ? FIXTURES.filter(file => file.type === kind) : FIXTURES
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || outputs.length)
    await route.fulfill({ json: { outputs: outputs.slice(offset, offset + limit), total: outputs.length } })
  })
  await page.route('**/api/v1/outputs', route => route.fulfill({ json: { outputs: FIXTURES, total: FIXTURES.length } }))
  await page.route('**/api/v1/outputs/*/metadata?*', async route => {
    requests.push(route.request().url())
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-2)!)
    await metadataGate.promise
    await route.fulfill({ json: metadata(name) })
    metadataReplies += 1
  })
  await page.route('**/api/v1/outputs/thumbnail/*', async route => {
    await imageGate.promise
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    await route.fulfill({ contentType: 'image/svg+xml', body: svg(name) })
  })
  await page.route('**/api/v1/file/gallery-*', async route => {
    await imageGate.promise
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    expect(name.endsWith('.png'), 'Browsing must not load any full video').toBe(true)
    await route.fulfill({ contentType: 'image/svg+xml', body: svg(name) })
  })
  return { releaseImages: imageGate.release, releaseMetadata: () => metadataGate.release(),
    holdMetadata: () => { metadataGate = gate() }, metadataReplies: () => metadataReplies, requests }
}
async function twoFrames(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}
const previews = (feed: Locator) => feed.locator('button[aria-label*="gallery-"]')
async function previewGeometry(feed: Locator) {
  return previews(feed).evaluateAll(nodes => nodes.slice(0, 4).map(node => {
    const box = (node.closest('[data-feed-index]') || node).getBoundingClientRect()
    return { name: node.getAttribute('aria-label'), x: box.x, y: box.y, width: box.width, height: box.height }
  }))
}
async function expectNoOverlap(feed: Locator) {
  const overlaps = await previews(feed).evaluateAll(nodes => {
    const boxes = nodes.map(node => {
      const rect = (node.closest('[data-feed-index]') || node).getBoundingClientRect()
      return { name: node.getAttribute('aria-label'), left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom }
    })
    const result: string[] = []
    for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) {
      if (Math.min(boxes[a].right, boxes[b].right) - Math.max(boxes[a].left, boxes[b].left) > 1
        && Math.min(boxes[a].bottom, boxes[b].bottom) - Math.max(boxes[a].top, boxes[b].top) > 1) result.push(`${boxes[a].name} overlaps ${boxes[b].name}`)
    }
    return result
  })
  expect(overlaps).toEqual([])
}
async function expectContained(page: Page, dialog: Locator) {
  const viewport = page.viewportSize()!, bounds = await dialog.locator('section').boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1)
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeInViewport()
}

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
  for (const view of ['One at a time', 'Grid', 'Mosaic']) {
    test(`Media ${view}: stable cards and responsive image details at ${viewport.width}x${viewport.height}`, async ({ page }) => {
      test.setTimeout(75_000)
      await page.setViewportSize(viewport)
      const session = await bootGalleryApp(page), fixtures = await installGalleryFixtures(page)
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      try {
        await page.getByRole('button', { name: 'Media', exact: true }).click()
        await page.getByRole('tab', { name: 'All', exact: true }).click()
        const feed = page.getByTestId('media-feed')
        const viewButton = page.getByRole('group', { name: 'Gallery layout' }).getByRole('button', { name: view, exact: true })
        await viewButton.click()
        await expect(viewButton).toHaveAttribute('aria-pressed', 'true')
        const first = feed.getByRole('button', { name: `Enlarge ${FIRST_IMAGE}`, exact: true })
        await expect(first).toBeVisible()
        await expect(feed.locator(`button[aria-label$="${VIDEO}"]`)).toBeAttached()
        await twoFrames(page)
        const before = await previewGeometry(feed)
        expect(before.length).toBeGreaterThanOrEqual(3)
        fixtures.releaseImages(); fixtures.releaseMetadata()
        await expect(first.locator('img')).toHaveJSProperty('naturalWidth', 480)
        if (view === 'One at a time') await expect.poll(fixtures.metadataReplies).toBeGreaterThan(0)
        await twoFrames(page)
        const after = await previewGeometry(feed)
        expect(after.map(box => box.name)).toEqual(before.map(box => box.name))
        for (let index = 0; index < before.length; index++) for (const key of ['x', 'y', 'width', 'height'] as const) {
          expect(Math.abs(after[index][key] - before[index][key]), `${before[index].name}: ${key} shifted`).toBeLessThanOrEqual(2)
        }
        await expectNoOverlap(feed)
        await page.screenshot({ path: test.info().outputPath('gallery-layout.png') })
        await expect(feed.locator('video')).toHaveCount(0)
        await page.getByRole('tab', { name: 'Images', exact: true }).click()
        await expect(first).toBeVisible()
        await expect(feed.locator(`button[aria-label$="${VIDEO}"]`)).toHaveCount(0)
        await expect(viewButton).toHaveAttribute('aria-pressed', 'true')
        fixtures.holdMetadata()
        await feed.evaluate(node => node.scrollTo({ top: node.scrollHeight, behavior: 'instant' }))
        const distant = feed.getByRole('button', { name: `Enlarge ${LAST_IMAGE}`, exact: true })
        await expect(distant).toBeInViewport({ timeout: 10_000 })
        const scrollBefore = await feed.evaluate(node => node.scrollTop)
        expect(scrollBefore).toBeGreaterThan(await feed.evaluate(node => node.clientHeight))
        await expectNoOverlap(feed)
        expect(await previews(feed).count()).toBeLessThan(30)
        await distant.click()
        const dialog = page.getByRole('dialog', { name: 'Image details', exact: true })
        await expect(dialog).toBeVisible()
        await expect(dialog.getByRole('status')).toContainText('Loading')
        await expectContained(page, dialog)
        fixtures.releaseMetadata()
        await expect(dialog).toContainText('fixture-portrait-model')
        await expect(dialog).toContainText('123456')
        await expect(dialog).toContainText('END OF LITERAL PROMPT')
        await page.screenshot({ path: test.info().outputPath('image-details-overview.png') })
        await expect(dialog.getByRole('img', { name: LAST_IMAGE, exact: true })).toHaveJSProperty('naturalWidth', 1600)
        await dialog.getByText('All saved information', { exact: true }).click()
        await expect(dialog.locator('pre')).toContainText(`job-${LAST_IMAGE}`)
        await expect(dialog.locator('pre')).toContainText('Do not crop the portrait')
        await expect(dialog.locator('pre')).toContainText(`task-${LAST_IMAGE}`)
        await expectContained(page, dialog)
        await page.screenshot({ path: test.info().outputPath('image-details.png') })
        await page.keyboard.press('Escape')
        await expect(dialog).toHaveCount(0)
        await expect(distant).toBeFocused()
        await expect(viewButton).toHaveAttribute('aria-pressed', 'true')
        expect(Math.abs(await feed.evaluate(node => node.scrollTop) - scrollBefore)).toBeLessThanOrEqual(2)
        expect(fixtures.requests.every(url => new URL(url).searchParams.get('workspace') === 'default')).toBe(true)
        expect(errors).toEqual([])
      } finally {
        fixtures.releaseImages(); fixtures.releaseMetadata()
        await closeApp(page, session)
      }
    })
  }
}

test('Media video dialog decodes, restores a seek and captures that frame as an input reference', async ({ page }) => {
  test.setTimeout(60_000)
  const session = await bootGalleryApp(page, async () => {
    await page.route('**/api/v1/model-options/*', route => route.fulfill({ json: {
      image_ref_choices: { choices: [['Subject', 'I']], default: 'I' }, max_image_refs: 4,
    } }))
  })
  const fixtures = await installGalleryFixtures(page)
  const bytes = await readFile(new URL('../../public/rig-previews/animation-run.webm', import.meta.url))
  await page.route(`**/api/v1/file/${VIDEO}*`, fulfillSeekable(bytes, 'video/webm'))
  fixtures.releaseImages(); fixtures.releaseMetadata()
  try {
    await page.getByRole('button', { name: 'Media', exact: true }).click()
    await page.getByRole('tab', { name: 'Videos', exact: true }).click()
    const feed = page.getByTestId('media-feed')
    const opener = feed.getByRole('button', { name: `Open video ${VIDEO}`, exact: true })
    await expect(opener).toBeVisible()
    await expect(feed.locator('video')).toHaveCount(0)
    await opener.click()
    const dialog = page.getByRole('dialog', { name: 'Video details', exact: true })
    const video = dialog.locator('video')
    await expect(video).toHaveJSProperty('videoWidth', 320)
    await video.evaluate(async node => {
      const media = node as HTMLVideoElement
      await media.play()
      media.pause()
      await new Promise<void>(resolve => { media.addEventListener('seeked', () => resolve(), { once: true }); media.currentTime = 0.3 })
    })
    const expectedFrame = await video.evaluate(node => {
      const media = node as HTMLVideoElement, canvas = document.createElement('canvas')
      canvas.width = media.videoWidth; canvas.height = media.videoHeight
      canvas.getContext('2d')!.drawImage(media, 0, 0)
      return canvas.toDataURL('image/png')
    })
    await page.keyboard.press('Escape')
    await expect(opener).toBeFocused()
    await expect(feed.locator('video')).toHaveCount(0)
    await opener.click()
    await expect(video).toHaveJSProperty('videoWidth', 320)
    await expect.poll(() => video.evaluate(node => (node as HTMLVideoElement).currentTime)).toBeCloseTo(0.3, 2)
    await page.keyboard.press('Escape')
    const card = opener.locator('xpath=ancestor::*[@data-feed-index]')
    const capture = card.getByRole('button', { name: 'Use current frame as reference image', exact: true })
    await capture.click()
    await expect(capture).toHaveClass(/text-accent-green/)
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await page.locator('[role="tablist"][data-navigation-category="direct-generation"]').getByRole('tab', { name: 'Video', exact: true }).click()
    const reference = page.locator('img[alt="Ref 1"]')
    await expect(reference).toBeVisible()
    await expect(reference).toHaveJSProperty('naturalWidth', 320)
    const actualFrame = await reference.evaluate(async node => {
      const response = await fetch((node as HTMLImageElement).src), blob = await response.blob()
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(blob)
      })
    })
    expect(actualFrame).toBe(expectedFrame)
    await page.screenshot({ path: test.info().outputPath('captured-video-reference.png') })
  } finally {
    fixtures.releaseImages(); fixtures.releaseMetadata()
    await closeApp(page, session)
  }
})

test('Media keeps audio controls and the move dialog visible on a narrow phone', async ({ page }) => {
  test.setTimeout(45_000)
  await page.setViewportSize({ width: 320, height: 740 })
  const session = await bootGalleryApp(page)
  const audio: ApiOutput = { ...FIXTURES[0], name: 'gallery-audio.wav', type: 'audio', mode: 'audio',
    url: '/api/v1/file/gallery-audio.wav?workspace=default', thumbnail_url: null }
  await page.route('**/api/v1/outputs?*', route => route.fulfill({ json: { outputs: [audio], total: 1 } }))
  try {
    await page.getByRole('button', { name: 'Media', exact: true }).click()
    await page.getByRole('tab', { name: 'Audio', exact: true }).click()
    const feed = page.getByTestId('media-feed'), card = feed.locator('[data-feed-index="0"]')
    const viewport = card.getByTestId('media-feed-viewport'), controls = card.locator('audio')
    await expect(controls).toBeVisible()
    const frame = (await viewport.boundingBox())!, player = (await controls.boundingBox())!
    expect(player.y).toBeGreaterThanOrEqual(frame.y)
    expect(player.y + player.height).toBeLessThanOrEqual(frame.y + frame.height + 1)
    expect(player.x).toBeGreaterThanOrEqual(frame.x)
    expect(player.x + player.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
    const move = card.getByRole('button', { name: 'Move to workspace', exact: true })
    await move.click()
    const dialog = page.getByRole('dialog', { name: 'Move to workspace', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('No other workspaces', { exact: true })).toBeInViewport()
    await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeInViewport()
    await page.keyboard.press('Escape')
    await expect(move).toBeFocused()
  } finally {
    await closeApp(page, session)
  }
})

test.describe('Media touch interactions', () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true })
  test('opens and closes image details by touch and scrolls the feed with a touch gesture', async ({ page }) => {
    test.setTimeout(45_000)
    const session = await bootGalleryApp(page), fixtures = await installGalleryFixtures(page)
    fixtures.releaseImages(); fixtures.releaseMetadata()
    try {
      await page.getByRole('button', { name: 'Media', exact: true }).tap()
      await page.getByRole('tab', { name: 'Images', exact: true }).tap()
      const feed = page.getByTestId('media-feed')
      const opener = feed.getByRole('button', { name: `Enlarge ${FIRST_IMAGE}`, exact: true })
      await expect(opener).toBeVisible()
      await opener.tap()
      const dialog = page.getByRole('dialog', { name: 'Image details', exact: true })
      await expect(dialog).toBeVisible()
      await expect(dialog).toContainText('fixture-portrait-model')
      await expectContained(page, dialog)
      await page.screenshot({ path: test.info().outputPath('touch-image-details.png') })
      await dialog.getByRole('button', { name: 'Close', exact: true }).tap()
      await expect(dialog).toHaveCount(0)
      const box = (await feed.boundingBox())!
      const cdp = await page.context().newCDPSession(page)
      await cdp.send('Input.synthesizeScrollGesture', {
        x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height * 0.7),
        yDistance: -250, speed: 500, gestureSourceType: 'touch',
      })
      await expect.poll(() => feed.evaluate(node => node.scrollTop)).toBeGreaterThan(100)
      await expectNoOverlap(feed)
      await cdp.detach()
    } finally {
      fixtures.releaseImages(); fixtures.releaseMetadata()
      await closeApp(page, session)
    }
  })
})
