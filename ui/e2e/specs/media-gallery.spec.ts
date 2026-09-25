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

test('mobile gallery keeps its width after returning from direct generation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const session = await bootGalleryApp(page), fixtures = await installGalleryFixtures(page)
  fixtures.releaseImages(); fixtures.releaseMetadata()
  try {
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await page.getByRole('tab', { name: 'Image', exact: true }).click()
    await expect(page.getByTestId('direct-generation-workspace')).toBeVisible()
    await page.getByRole('button', { name: 'Media', exact: true }).click()
    await page.getByRole('tab', { name: 'Images', exact: true }).click()
    const feed = page.getByTestId('media-feed')
    const card = feed.locator('[data-feed-index="0"]')
    await expect(card).toBeVisible()
    await expect.poll(async () => (await card.boundingBox())!.width).toBeGreaterThan(350)
    const bounds = (await card.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
    await page.screenshot({ path: test.info().outputPath('mobile-return.png') })
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await expect(page.getByTestId('direct-generation-workspace')).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Image', exact: true })).toHaveAttribute('aria-selected', 'true')
  } finally { await closeApp(page, session) }
})

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
        await distant.scrollIntoViewIfNeeded()
        await twoFrames(page)
        const scrollBefore = await feed.evaluate(node => node.scrollTop)
        expect(scrollBefore).toBeGreaterThan(await feed.evaluate(node => node.clientHeight))
        await expectNoOverlap(feed)
        expect(await previews(feed).count()).toBeLessThan(FIXTURES.filter(file => file.type === 'image').length)
        await distant.click()
        const dialog = page.getByRole('dialog', { name: 'Image details', exact: true })
        await expect(dialog).toBeVisible()
        const scrollAtOpen = await feed.evaluate(node => node.scrollTop)
        expect(Math.abs(scrollAtOpen - scrollBefore), 'Opening details moved the gallery').toBeLessThanOrEqual(2)
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
        expect(Math.abs(await feed.evaluate(node => node.scrollTop) - scrollAtOpen)).toBeLessThanOrEqual(2)
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
      const box = (await opener.boundingBox())!
      const cdp = await page.context().newCDPSession(page)
      const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2)
      // dispatchTouchEvent exercises the mobile pan; synthesizeScrollGesture
      // does not scroll even a plain overflowing div in headless Chromium.
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] })
      for (let step = 1; step <= 10; step++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y - step * 15 }] })
        await twoFrames(page)
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
      await expect.poll(() => feed.evaluate(node => node.scrollTop)).toBeGreaterThan(100)
      await expectNoOverlap(feed)
      await cdp.detach()
    } finally {
      fixtures.releaseImages(); fixtures.releaseMetadata()
      await closeApp(page, session)
    }
  })
})

// A library that mixes every kind the gallery shows. Images carry the pixel
// size the listing now reports; videos, scenes, comics, audio and 3D fall back.
const MIXED: ApiOutput[] = Array.from({ length: 48 }, (_, index) => {
  const kinds = ['image', 'scene', 'audio', 'image', 'comic', 'video', 'model3d', 'image'] as const
  const type = kinds[index % kinds.length]
  const stem = `gallery-${String(index).padStart(3, '0')}`
  const name = `${stem}.${{ image: 'png', video: 'mp4', audio: 'mp3', scene: 'scene.json', comic: 'comic.json', model3d: 'glb' }[type]}`
  const thumbnail_url = type === 'scene' ? `/api/v1/file/${stem}.preview.png?workspace=default`
    : type === 'comic' ? `/api/v1/file/${stem}.comic.preview.png?workspace=default`
    : type === 'image' || type === 'video' ? `/api/v1/outputs/thumbnail/${name}?workspace=default` : null
  const size = type === 'image' ? (index % 2 === 0 ? { width: 480, height: 1600, color: '#3366aa' } : { width: 1600, height: 480, color: '#aa4433' }) : {}
  return { name, type, ...size, mode: type === 'audio' ? 'audio' : 'image', favorite: false, size: 1000,
    created_at: 1_790_000_000 - index, completed_at: 1_790_000_020 - index, completion_time_source: 'metadata',
    url: `/api/v1/file/${name}?workspace=default`, thumbnail_url }
})
const VIEWS = ['One at a time', 'Grid', 'Mosaic'] as const

async function bootMixedGallery(page: Page, options: { holdImages?: boolean; beforeGoto?: () => Promise<void>; removed?: Set<string> } = {}) {
  const session = await bootGalleryApp(page, options.beforeGoto), fixtures = await installGalleryFixtures(page)
  if (!options.holdImages) fixtures.releaseImages()
  fixtures.releaseMetadata()
  await page.route('**/api/v1/outputs?*', route => {
    const url = new URL(route.request().url())
    // Like the server, a listing never returns outputs that were deleted or moved away.
    const listed = MIXED.filter(file => !options.removed?.has(file.name))
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || listed.length)
    return route.fulfill({ json: { outputs: listed.slice(offset, offset + limit), total: listed.length } })
  })
  await page.route('**/api/v1/file/gallery-*', route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    return name.endsWith('.png') ? route.fulfill({ contentType: 'image/svg+xml', body: svg(name) }) : route.fulfill({ status: 404, body: '' })
  })
  await page.getByRole('button', { name: 'Media', exact: true }).click()
  await page.getByRole('tab', { name: 'All', exact: true }).click()
  return Object.assign(session, { releaseImages: fixtures.releaseImages })
}
async function chooseView(page: Page, view: string) {
  const button = page.getByRole('group', { name: 'Gallery layout' }).getByRole('button', { name: view, exact: true })
  await button.click()
  await expect(button).toHaveAttribute('aria-pressed', 'true')
  await twoFrames(page)
}
/** Rows and tiles in the list, relative to the feed's top edge. */
async function rows(feed: Locator) {
  return feed.evaluate(node => {
    const top = node.getBoundingClientRect().top
    const list = node.querySelector<HTMLElement>(':scope > div.relative')!
    const boxes = [...list.children].map(child => {
      const rect = child.getBoundingClientRect()
      return { label: child.getAttribute('data-feed-index') ?? child.querySelector('[aria-label]')?.getAttribute('aria-label') ?? child.textContent ?? '',
        left: rect.left, right: rect.right, top: rect.top - top, bottom: rect.bottom - top, height: rect.height }
    })
    return { boxes, listHeight: list.style.height, listRight: list.getBoundingClientRect().right, viewport: node.clientHeight, scrollTop: node.scrollTop, max: node.scrollHeight - node.clientHeight }
  })
}
function overlaps(boxes: Array<{ label: string; left: number; right: number; top: number; bottom: number }>) {
  const found: string[] = []
  for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) {
    if (Math.min(boxes[a].right, boxes[b].right) - Math.max(boxes[a].left, boxes[b].left) > 1
      && Math.min(boxes[a].bottom, boxes[b].bottom) - Math.max(boxes[a].top, boxes[b].top) > 1) found.push(`${boxes[a].label} × ${boxes[b].label}`)
  }
  return found
}

test.describe('Media gallery geometry', () => {
  for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    test(`the layout switcher sits in its own bar above the rows at ${viewport.width}x${viewport.height}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const session = await bootMixedGallery(page)
      try {
        const feed = page.getByTestId('media-feed')
        for (const view of VIEWS) {
          await chooseView(page, view)
          const switcher = (await page.getByRole('group', { name: 'Gallery layout' }).boundingBox())!
          const area = (await feed.boundingBox())!
          expect(switcher.y + switcher.height, `${view}: switcher above the rows`).toBeLessThanOrEqual(area.y + 1)
          expect(switcher.x + switcher.width, `${view}: switcher inside the rows column`).toBeLessThanOrEqual(area.x + area.width + 1)
          expect(switcher.x).toBeGreaterThanOrEqual(area.x - 1)
        }
      } finally {
        await closeApp(page, session)
      }
    })
  }

  test('rows stay put and scrolling stays exact while a phone toolbar slides away', async ({ page }) => {
    test.setTimeout(90_000)
    // The small viewport (toolbar shown) is the window; sliding the toolbar
    // away grows the dynamic viewport and #root, as mobile browsers do.
    await page.setViewportSize({ width: 390, height: 768 })
    const session = await bootMixedGallery(page)
    const toolbar = (extra: number) => page.evaluate(value => {
      Object.defineProperty(window, 'innerHeight', { configurable: true, get: () => 768 + value })
      document.getElementById('root')!.style.height = `${768 + value}px`
    }, extra)
    try {
      const feed = page.getByTestId('media-feed')
      for (const view of VIEWS) {
        await toolbar(0)
        await chooseView(page, view)
        await feed.evaluate(node => node.scrollTo({ top: 0, behavior: 'instant' }))
        await twoFrames(page)
        const start = await rows(feed)
        let last = 0
        for (let step = 0; step < 14; step++) {
          // The browser clamps a scroll to the bottom it had at that moment,
          // and again if the toolbar then shortens the scrollable range.
          const maxAtScroll = await feed.evaluate(node => {
            node.scrollBy({ top: 260, behavior: 'instant' })
            return node.scrollHeight - node.clientHeight
          })
          await toolbar(step % 2 === 0 ? 76 : 0)
          await twoFrames(page)
          const now = await rows(feed)
          expect(now.listHeight, `${view} step ${step}: rows re-flowed`).toBe(start.listHeight)
          expect(Math.abs(now.scrollTop - Math.min(last + 260, maxAtScroll, now.max)), `${view} step ${step}: scroll jumped`).toBeLessThanOrEqual(2)
          expect(overlaps(now.boxes), `${view} step ${step}`).toEqual([])
          for (const box of now.boxes) expect(box.height, `${view}: ${box.label} taller than the screen`).toBeLessThanOrEqual(start.viewport + 1)
          last = now.scrollTop
        }
        if (view === 'One at a time') {
          const cards = (await rows(feed)).boxes.sort((a, b) => a.top - b.top)
          for (let index = 1; index < cards.length; index++) expect(Math.round(cards[index].top - cards[index - 1].bottom)).toBe(12)
        }
      }
    } finally {
      await closeApp(page, session)
    }
  })

  test('a real resize and a view switch keep the same item in view', async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width: 390, height: 844 })
    const session = await bootMixedGallery(page)
    const firstVisible = (feed: Locator) => rows(feed).then(state => state.boxes.filter(box => box.bottom > 0).sort((a, b) => a.top - b.top)[0])
    try {
      const feed = page.getByTestId('media-feed')
      for (const view of VIEWS) {
        await page.setViewportSize({ width: 390, height: 844 })
        await chooseView(page, view)
        await feed.evaluate(node => node.scrollTo({ top: 1500, behavior: 'instant' }))
        await twoFrames(page)
        const before = await firstVisible(feed)
        await page.setViewportSize({ width: 390, height: 700 })
        await twoFrames(page)
        const after = await firstVisible(feed)
        expect(after.label, `${view}: another item took its place`).toBe(before.label)
        expect(Math.abs(after.top - before.top), `${view}: item moved`).toBeLessThanOrEqual(2)
      }
      await page.setViewportSize({ width: 390, height: 844 })
      await chooseView(page, 'One at a time')
      await feed.evaluate(node => node.scrollTo({ top: 5000, behavior: 'instant' }))
      await twoFrames(page)
      const card = await firstVisible(feed)
      const name = MIXED[Number(card.label)].name
      await chooseView(page, 'Grid')
      await expect(feed.locator(`[aria-label$="${name}"], button:has-text("${name}")`).first()).toBeInViewport()
    } finally {
      await closeApp(page, session)
    }
  })

  test('mosaic rows are justified and keep each output aspect', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Mosaic')
      await expect(feed.getByRole('button', { name: 'Enlarge gallery-000.png', exact: true })).toBeVisible()
      const state = await rows(feed)
      const lines = new Map<number, typeof state.boxes>()
      for (const box of state.boxes) lines.set(Math.round(box.top), [...(lines.get(Math.round(box.top)) ?? []), box])
      const ordered = [...lines.entries()].sort((a, b) => a[0] - b[0]).slice(0, 3)
      expect(ordered.length).toBe(3)
      for (const [, line] of ordered) expect(Math.abs(Math.max(...line.map(box => box.right)) - (state.listRight))).toBeLessThanOrEqual(1)
      const portrait = state.boxes.find(box => box.label.endsWith('gallery-000.png'))!
      expect((portrait.right - portrait.left) / portrait.height).toBeCloseTo(0.4, 1)
      const landscape = state.boxes.find(box => box.label.endsWith('gallery-003.png'))!
      expect((landscape.right - landscape.left) / landscape.height).toBeCloseTo(3, 1)
    } finally {
      await closeApp(page, session)
    }
  })
})

const dialogTitle = (page: Page) => page.getByRole('dialog').locator('h2')

/** Two-finger touch gesture through the Chrome protocol: real multi-touch,
 *  which Playwright's single-point touchscreen cannot produce. */
async function touch(page: Page) {
  const cdp = await page.context().newCDPSession(page)
  const send = (type: string, touchPoints: Array<{ x: number; y: number; id: number }>) =>
    cdp.send('Input.dispatchTouchEvent', { type, touchPoints: touchPoints.map(({ id, ...point }) => ({ ...point, id, radiusX: 4, radiusY: 4, force: 1 })) })
  return {
    async pinch(center: { x: number; y: number }, from: number, to: number) {
      const points = (spread: number) => [{ x: center.x - spread / 2, y: center.y, id: 1 }, { x: center.x + spread / 2, y: center.y, id: 2 }]
      await send('touchStart', points(from))
      for (let step = 1; step <= 10; step++) await send('touchMove', points(from + (to - from) * step / 10))
      await send('touchEnd', [])
    },
    async longPress(point: { x: number; y: number }) {
      await send('touchStart', [{ ...point, id: 1 }])
      await page.waitForTimeout(700)
      await send('touchEnd', [])
    },
  }
}

test.describe('Media gallery viewer and tools', () => {
  test('the details dialog steps through every output with buttons, keys and swipes', async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      await feed.getByRole('button', { name: `Enlarge ${MIXED[0].name}`, exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialogTitle(page)).toHaveText(MIXED[0].name)
      await expect(dialog).toContainText(`1 of ${MIXED.length}`)
      await expect(dialog.getByRole('button', { name: 'Previous', exact: true })).toHaveCount(0)

      // Scenes and audio are part of the walk, with their own preview.
      await dialog.getByRole('button', { name: 'Next', exact: true }).click()
      await expect(page.getByRole('dialog', { name: 'Output details', exact: true })).toBeVisible()
      await expect(dialogTitle(page)).toHaveText(MIXED[1].name)
      await expect(dialog.getByRole('button', { name: 'Open in its editor', exact: true })).toBeVisible()
      await page.keyboard.press('ArrowRight')
      await expect(dialogTitle(page)).toHaveText(MIXED[2].name)
      await expect(dialog.locator('audio')).toHaveCount(1)
      await page.keyboard.press('ArrowRight')
      await expect(dialogTitle(page)).toHaveText(MIXED[3].name)
      await page.keyboard.press('ArrowLeft')
      await expect(dialogTitle(page)).toHaveText(MIXED[2].name)
      await page.keyboard.press('ArrowRight')

      // A horizontal drag on the picture is a swipe to the next item.
      const box = (await dialog.getByTestId('zoomable-image').boundingBox())!
      await page.mouse.move(box.x + box.width * 0.7, box.y + box.height / 2)
      await page.mouse.down()
      await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2, { steps: 6 })
      await page.mouse.up()
      await expect(dialogTitle(page)).toHaveText(MIXED[4].name)

      // Walk far beyond the rows mounted behind the dialog.
      for (let step = 0; step < 19; step++) await page.keyboard.press('ArrowRight')
      await expect(dialogTitle(page)).toHaveText(MIXED[23].name)
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      // Closing leaves the gallery on the item that was being viewed.
      const tile = feed.locator('[data-gallery-index="23"]')
      await expect(tile).toBeInViewport()
      await expect(tile).toHaveAttribute('aria-current', 'true')
    } finally {
      await closeApp(page, session)
    }
  })

  test('all three views offer the one-up card actions in the details dialog', async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    const labels = (bar: Locator) => bar.locator('button').evaluateAll(nodes =>
      nodes.map(node => node.getAttribute('title') || node.getAttribute('aria-label') || '').filter(Boolean).sort())
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'One at a time')
      const card = feed.locator('[data-feed-index="0"]')
      await expect(card.getByTestId('output-actions').getByTitle('Copy prompt')).toBeVisible()
      const cardActions = await labels(card.getByTestId('output-actions'))
      expect(cardActions).toEqual(expect.arrayContaining(['Download', 'Move to workspace', 'Add to favorites', 'Delete output', 'Copy prompt']))
      for (const view of VIEWS) {
        await chooseView(page, view)
        await feed.getByRole('button', { name: `Enlarge ${MIXED[0].name}`, exact: true }).click()
        const bar = page.getByRole('dialog').getByTestId('output-actions')
        await expect(bar.getByTitle('Copy prompt')).toBeVisible()
        expect(await labels(bar), `${view}: dialog actions`).toEqual(cardActions)
        await page.keyboard.press('Escape')
      }

      // Outputs without a picture get the same dialog and their actions.
      await chooseView(page, 'Grid')
      await feed.getByRole('button', { name: MIXED[2].name, exact: true }).click()
      const audio = page.getByRole('dialog', { name: 'Output details', exact: true })
      await expect(audio.locator('audio')).toHaveCount(1)
      await expect(audio.getByTestId('output-actions').getByTitle('Download')).toBeVisible()
    } finally {
      await closeApp(page, session)
    }
  })

  test('two images can be compared side by side from the dialog or a selection', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    const images = MIXED.filter(file => file.type === 'image')
    const captions = () => page.getByTestId('compare-view').locator('figcaption')
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      await feed.getByRole('button', { name: `Enlarge ${images[0].name}`, exact: true }).click()
      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Compare', exact: true }).click()
      await expect(dialog.getByTestId('zoomable-image')).toHaveCount(2)
      await expect(captions()).toHaveText([`A${images[0].name}`, `B${images[1].name}`])
      await expect(dialog).toContainText(`2 of ${images.length}`)
      // Stepping changes B only, skipping audio, scenes and A itself.
      await page.keyboard.press('ArrowRight')
      await expect(captions()).toHaveText([`A${images[0].name}`, `B${images[2].name}`])
      await expect(dialogTitle(page)).toHaveText(images[0].name)
      await page.keyboard.press('ArrowLeft')
      await expect(captions()).toHaveText([`A${images[0].name}`, `B${images[1].name}`])
      await expect(dialog.getByRole('button', { name: 'Previous', exact: true })).toHaveCount(0)

      await dialog.getByRole('button', { name: 'Swap A and B', exact: true }).click()
      await expect(captions()).toHaveText([`A${images[1].name}`, `B${images[0].name}`])
      await expect(dialogTitle(page)).toHaveText(images[1].name)
      await dialog.getByRole('button', { name: 'Stop comparing', exact: true }).click()
      await expect(page.getByTestId('compare-view')).toHaveCount(0)
      await page.keyboard.press('Escape')

      await page.getByRole('button', { name: 'Select', exact: true }).click()
      await feed.getByRole('checkbox', { name: images[2].name, exact: true }).click()
      await expect(page.getByRole('button', { name: 'Compare the two images' })).toHaveCount(0)
      await feed.getByRole('checkbox', { name: images[3].name, exact: true }).click()
      await page.getByRole('button', { name: 'Compare the two images', exact: true }).click()
      await expect(captions()).toHaveText([`A${images[2].name}`, `B${images[3].name}`])
      await expect(feed.getByRole('checkbox')).toHaveCount(0)
    } finally {
      await closeApp(page, session)
    }
  })

  test('comparing on a phone stacks both images fully on screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const session = await bootMixedGallery(page)
    const images = MIXED.filter(file => file.type === 'image')
    try {
      await chooseView(page, 'Grid')
      await page.getByTestId('media-feed').getByRole('button', { name: `Enlarge ${images[0].name}`, exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Compare', exact: true }).click()
      const pictures = page.getByTestId('compare-view').locator('img')
      await expect(pictures).toHaveCount(2)
      for (const picture of await pictures.all()) {
        await expect(picture).toHaveJSProperty('complete', true)
        await expect(picture).toBeInViewport({ ratio: 1 })
      }
      const [top, bottom] = await pictures.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect()))
      expect(bottom.top).toBeGreaterThanOrEqual(top.bottom - 1)
    } finally {
      await closeApp(page, session)
    }
  })

  test('sizes and colours worked out later settle into the list without a reload', async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize({ width: 1280, height: 800 })
    const video = MIXED.find(file => file.type === 'video')!
    let ready = false
    const requested: string[][] = []
    const session = await bootMixedGallery(page)
    await page.route('**/api/v1/outputs/facts', route => {
      const names = (route.request().postDataJSON() as { names: string[] }).names
      requested.push(names)
      return route.fulfill({ json: { facts: ready ? { [video.name]: { width: 720, height: 1280, color: '#224466' } } : {} } })
    })
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Mosaic')
      const tile = feed.locator(`[data-gallery-index="${MIXED.indexOf(video)}"]`)
      const aspect = () => tile.evaluate(node => node.getBoundingClientRect().width / node.getBoundingClientRect().height)
      expect(await aspect()).toBeCloseTo(16 / 9, 1)
      // Only the outputs still missing facts are asked about.
      await expect.poll(() => requested.length, { timeout: 10_000 }).toBeGreaterThan(0)
      expect(requested[0]).toContain(video.name)
      expect(requested[0]).not.toContain(MIXED.find(file => file.type === 'audio')!.name)
      ready = true
      await expect.poll(aspect, { timeout: 15_000 }).toBeCloseTo(720 / 1280, 1)
    } finally {
      await closeApp(page, session)
    }
  })

  test('grid and mosaic group outputs by day and follow the chosen order', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    const now = Math.floor(Date.now() / 1000)
    const day = 86_400
    const dated = MIXED.slice(0, 12).map((file, index) => ({
      ...file,
      created_at: now - (index < 4 ? 60 * index : index < 8 ? day + 60 * index : 3 * day + 60 * index),
      completed_at: undefined,
      favorite: index === 9,
    }))
    const orders: string[] = []
    await page.route('**/api/v1/outputs?*', route => {
      const order = new URL(route.request().url()).searchParams.get('order') || 'newest'
      orders.push(order)
      const listed = order === 'oldest' ? [...dated].reverse()
        : order === 'favorites' ? [...dated].sort((a, b) => Number(b.favorite) - Number(a.favorite)) : dated
      return route.fulfill({ json: { outputs: listed, total: listed.length } })
    })
    try {
      const feed = page.getByTestId('media-feed')
      await page.getByRole('tab', { name: 'Images', exact: true }).click()
      await page.getByRole('tab', { name: 'All', exact: true }).click()
      await chooseView(page, 'Grid')
      const headings = feed.getByRole('heading', { level: 3 })
      await expect(headings).toHaveText(['Today', 'Yesterday', /\w+day, \w+ \d+/])
      await expect(headings.nth(0)).toBeInViewport()
      await chooseView(page, 'Mosaic')
      await expect(headings).toHaveCount(3)
      await chooseView(page, 'One at a time')
      await expect(headings).toHaveCount(0)

      await chooseView(page, 'Grid')
      await page.getByRole('combobox', { name: 'Order' }).selectOption('oldest')
      await expect.poll(() => orders.at(-1)).toBe('oldest')
      await expect(headings).toHaveText([/\w+day, \w+ \d+/, 'Yesterday', 'Today'])
      await expect(feed.locator('[data-gallery-index="0"]')).toContainText(dated.at(-1)!.name)
      await page.getByRole('combobox', { name: 'Order' }).selectOption('favorites')
      await expect.poll(() => orders.at(-1)).toBe('favorites')
      await expect(feed.locator('[data-gallery-index="0"]')).toContainText(dated[9].name)
      await expect(headings).toHaveCount(0)
      // The choice persists for the next session.
      expect(await page.evaluate(() => localStorage.getItem('hocuspocus_gallery_order'))).toBe('favorites')
    } finally {
      await closeApp(page, session)
    }
  })

  test('the gallery toolbar searches the library and clears back to the full list', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    const searches: Array<string | null> = []
    await page.route('**/api/v1/outputs?*', route => {
      const url = new URL(route.request().url())
      const search = url.searchParams.get('search')
      const kind = url.searchParams.get('media_type')
      searches.push(search)
      const listed = MIXED.filter(file => (!kind || file.type === kind) && (!search || file.name.includes(search)))
      return route.fulfill({ json: { outputs: listed, total: listed.length } })
    })
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      const box = page.getByRole('searchbox', { name: 'Search prompts, models and modes' })
      await box.fill('gallery-01')
      await expect.poll(() => searches.at(-1)).toBe('gallery-01')
      await expect(page.getByRole('search')).toContainText('10 results')
      await expect(feed.locator('[data-gallery-index]')).toHaveCount(10)
      await page.getByRole('button', { name: 'Clear search', exact: true }).click()
      await expect.poll(() => searches.at(-1)).toBeNull()
      await expect.poll(() => feed.locator('[data-gallery-index]').count()).toBeGreaterThan(10)

      // Clearing on a filtered tab reloads that tab's full list.
      await page.getByRole('tab', { name: 'Images', exact: true }).click()
      await box.fill('gallery-00')
      await expect.poll(() => searches.at(-1)).toBe('gallery-00')
      const images = MIXED.filter(file => file.type === 'image')
      await expect(feed.locator('[data-gallery-index]')).toHaveCount(images.filter(file => file.name.includes('gallery-00')).length)
      await box.fill('')
      await expect.poll(() => searches.at(-1)).toBeNull()
      await expect.poll(() => feed.locator('[data-gallery-index]').count()).toBeGreaterThan(4)

      await box.fill('nothing-like-this')
      await expect(page.getByText('No results for “nothing-like-this”')).toBeVisible()
      await expect(page.getByText('will appear here')).toHaveCount(0)
      await page.getByRole('main').getByRole('button', { name: 'Clear search', exact: true }).last().click()
      await expect(box).toHaveValue('')
    } finally {
      await closeApp(page, session)
    }
  })

  test('deleting from the dialog steps to the next output', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const deleted: string[] = []
    const removed = new Set<string>()
    const session = await bootMixedGallery(page, { removed })
    await page.route(url => /\/api\/v1\/outputs\/[^/]+$/.test(url.pathname), route => {
      if (route.request().method() !== 'DELETE') return route.fallback()
      deleted.push(decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!))
      removed.add(deleted.at(-1)!)
      return route.fulfill({ json: { ok: true } })
    })
    try {
      await chooseView(page, 'Mosaic')
      await page.getByTestId('media-feed').getByRole('button', { name: `Enlarge ${MIXED[3].name}`, exact: true }).click()
      const bar = page.getByRole('dialog').getByTestId('output-actions')
      // Cancelling the confirmation deletes nothing.
      await bar.getByTitle('Delete output').click()
      const confirm = page.getByRole('dialog', { name: 'Delete this output?', exact: true })
      await expect(confirm).toContainText(MIXED[3].name)
      await expect(confirm.getByRole('button').first()).toHaveText('Cancel')
      await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(confirm).toHaveCount(0)
      await expect(dialogTitle(page)).toHaveText(MIXED[3].name)
      expect(deleted).toEqual([])
      await bar.getByTitle('Delete output').click()
      await confirm.getByRole('button', { name: 'Delete', exact: true }).click()
      await expect(dialogTitle(page)).toHaveText(MIXED[4].name)
      await expect.poll(() => deleted).toEqual([MIXED[3].name])
      await expect(page.getByTestId('media-feed').getByText(MIXED[3].name, { exact: true })).toHaveCount(0)
    } finally {
      await closeApp(page, session)
    }
  })

  test('the details image zooms with a double click and pans while zoomed', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    try {
      await chooseView(page, 'Grid')
      await page.getByTestId('media-feed').getByRole('button', { name: `Enlarge ${MIXED[3].name}`, exact: true }).click()
      const zoom = page.getByRole('dialog').getByTestId('zoomable-image')
      await expect(zoom.locator('img')).toHaveJSProperty('complete', true)
      const box = (await zoom.boundingBox())!
      const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
      await page.mouse.dblclick(center.x, center.y)
      await expect(zoom).toHaveAttribute('data-zoom', '2.50')
      const before = await zoom.locator('img').evaluate(node => node.style.transform)
      await page.mouse.move(center.x, center.y)
      await page.mouse.down()
      await page.mouse.move(center.x - 120, center.y + 40, { steps: 5 })
      await page.mouse.up()
      expect(await zoom.locator('img').evaluate(node => node.style.transform)).not.toBe(before)
      // A drag while zoomed pans; it never counts as a swipe.
      await expect(page.getByRole('dialog').locator('h2')).toHaveText(MIXED[3].name)
      await page.mouse.dblclick(center.x, center.y)
      await expect(zoom).toHaveAttribute('data-zoom', '1.00')
    } finally {
      await closeApp(page, session)
    }
  })

  test('tiles paint the output colour until the preview arrives', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page, { holdImages: true })
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      const tile = feed.locator('[data-gallery-index="0"]')
      await expect(tile.locator('span[aria-hidden="true"][style*="background-color"]')).toHaveCSS('background-color', 'rgb(51, 102, 170)')
      await expect(tile.locator('img')).toHaveCSS('opacity', '0')
      session.releaseImages()
      await expect(tile.locator('img')).toHaveCSS('opacity', '1')
      await expect(tile.locator('span[aria-hidden="true"][style*="background-color"]')).toHaveCount(0)
    } finally {
      await closeApp(page, session)
    }
  })

  test('arrows move through the grid a row at a time and Enter opens the item', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      await page.locator('body').click({ position: { x: 5, y: 5 } })
      const current = feed.locator('[aria-current="true"]')
      await expect(current).toHaveAttribute('data-gallery-index', '0')
      await page.keyboard.press('ArrowRight')
      await expect(current).toHaveAttribute('data-gallery-index', '1')
      const columns = await feed.evaluate(node => new Set([...node.querySelectorAll<HTMLElement>('[data-gallery-index]')]
        .filter(tile => Math.round(tile.getBoundingClientRect().top) === Math.round(node.querySelector<HTMLElement>('[data-gallery-index="0"]')!.getBoundingClientRect().top))
        .map(tile => tile.dataset.galleryIndex)).size)
      await page.keyboard.press('ArrowDown')
      await expect(current).toHaveAttribute('data-gallery-index', String(1 + columns))
      for (let step = 0; step < 6; step++) await page.keyboard.press('j')
      await expect(current).toBeInViewport()
      const index = Number(await current.getAttribute('data-gallery-index'))
      await page.keyboard.press('ArrowLeft')
      await page.keyboard.press('ArrowRight')
      await page.keyboard.press('Enter')
      if (MIXED[index].type === 'image' || MIXED[index].type === 'video') {
        await expect(dialogTitle(page)).toHaveText(MIXED[index].name)
      }
    } finally {
      await closeApp(page, session)
    }
  })

  test('multi-select favourites, moves and deletes several outputs at once', async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width: 1280, height: 800 })
    const calls: string[] = []
    const favorites = new Set<string>()
    const removed = new Set<string>()
    const session = await bootMixedGallery(page, {
      removed,
      beforeGoto: async () => {
        await page.route('**/api/v1/workspaces', route => route.request().method() === 'GET'
          ? route.fulfill({ json: { workspaces: [{ name: 'default' }, { name: 'archive' }] } }) : route.fallback())
      },
    })
    await page.route('**/api/v1/favorites/*', route => {
      const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
      calls.push(`favorite ${name}`)
      if (favorites.has(name)) favorites.delete(name)
      else favorites.add(name)
      return route.fulfill({ json: { name, favorite: favorites.has(name) } })
    })
    await page.route(url => /\/api\/v1\/outputs\/[^/]+(\/move)?$/.test(url.pathname), route => {
      const parts = new URL(route.request().url()).pathname.split('/')
      const move = parts.at(-1) === 'move'
      const name = decodeURIComponent(parts.at(move ? -2 : -1)!)
      calls.push(`${move ? 'move' : route.request().method().toLowerCase()} ${name}`)
      removed.add(name)
      return route.fulfill({ json: { ok: true } })
    })
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      await page.getByRole('button', { name: 'Select', exact: true }).click()
      const box = (index: number) => feed.getByRole('checkbox', { name: MIXED[index].name, exact: true })
      await box(0).click()
      await box(3).click({ modifiers: ['Shift'] })
      await expect(page.getByRole('toolbar')).toContainText('4 selected')
      await box(2).click()
      await expect(box(2)).toHaveAttribute('aria-checked', 'false')

      await page.getByRole('button', { name: 'Favorite', exact: true }).click()
      await expect.poll(() => calls.filter(call => call.startsWith('favorite')).sort()).toEqual([0, 1, 3].map(index => `favorite ${MIXED[index].name}`))
      await expect(page.getByRole('toolbar')).toContainText('Tap items to select them')

      await box(5).click()
      await page.getByRole('button', { name: 'Move', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'archive', exact: true }).click()
      await expect.poll(() => calls.includes(`move ${MIXED[5].name}`)).toBe(true)
      await expect(feed.getByText(MIXED[5].name, { exact: true })).toHaveCount(0)

      await page.getByRole('button', { name: 'Select', exact: true }).click()
      await box(0).click()
      await box(1).click()
      await page.getByRole('button', { name: 'Delete', exact: true }).click()
      const confirm = page.getByRole('dialog', { name: 'Delete 2 outputs?', exact: true })
      await expect(confirm).toContainText('Delete 2 items? This cannot be undone.')
      await page.keyboard.press('Escape')
      await expect(confirm).toHaveCount(0)
      expect(calls.filter(call => call.startsWith('delete'))).toEqual([])
      await page.getByRole('button', { name: 'Delete', exact: true }).click()
      await confirm.getByRole('button', { name: 'Delete', exact: true }).click()
      await expect.poll(() => calls.filter(call => call.startsWith('delete')).sort()).toEqual([0, 1].map(index => `delete ${MIXED[index].name}`))
      await expect(feed.getByRole('checkbox')).toHaveCount(0)
      await expect(feed.getByText(MIXED[0].name, { exact: true })).toHaveCount(0)
      await expect(feed.locator('[data-gallery-index="0"]')).toContainText(MIXED[2].name)
    } finally {
      await closeApp(page, session)
    }
  })

  test('each list returns to where the reader left it', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'One at a time')
      await feed.evaluate(node => node.scrollTo({ top: 4200, behavior: 'instant' }))
      await twoFrames(page)
      const before = await rows(feed).then(state => state.boxes.filter(box => box.bottom > 0).sort((a, b) => a.top - b.top)[0])
      await page.getByRole('tab', { name: 'Images', exact: true }).click()
      await expect.poll(() => feed.evaluate(node => node.scrollTop)).toBeLessThan(30)
      await page.getByRole('tab', { name: 'All', exact: true }).click()
      await expect.poll(async () => (await rows(feed)).boxes.filter(box => box.bottom > 0).sort((a, b) => a.top - b.top)[0]?.label).toBe(before.label)
      const after = await rows(feed).then(state => state.boxes.filter(box => box.bottom > 0).sort((a, b) => a.top - b.top)[0])
      expect(Math.abs(after.top - before.top)).toBeLessThanOrEqual(2)
    } finally {
      await closeApp(page, session)
    }
  })
})

test.describe('Media gallery on a touch phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('history opens from the toolbar and nothing floats over the cards', async ({ page }) => {
    const session = await bootMixedGallery(page)
    try {
      await chooseView(page, 'One at a time')
      await expect(page.getByRole('button', { name: 'Show thumbnails' })).toHaveCount(0)
      await page.getByRole('button', { name: 'History', exact: true }).click()
      const panel = page.locator('aside').filter({ hasText: 'History' })
      await expect(panel).toBeInViewport()
      await panel.getByRole('button', { name: MIXED[7].name, exact: true }).click()
      await expect(panel).not.toBeInViewport()
      await expect(page.getByTestId('media-feed').locator('[data-feed-index="7"]')).toBeInViewport()
    } finally {
      await closeApp(page, session)
    }
  })

  test('search opens over the toolbar on a phone and Escape closes it', async ({ page }) => {
    const session = await bootMixedGallery(page)
    try {
      await chooseView(page, 'Grid')
      await expect(page.getByRole('searchbox')).toHaveCount(0)
      await page.getByRole('button', { name: 'Search', exact: true }).click()
      const box = page.getByRole('searchbox', { name: 'Search prompts, models and modes' })
      await expect(box).toBeFocused()
      await expect(box).toBeInViewport()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('searchbox')).toHaveCount(0)
      await expect(page.getByRole('group', { name: 'Gallery layout' })).toBeVisible()
    } finally {
      await closeApp(page, session)
    }
  })

  test('pinching the grid changes its columns and the choice persists', async ({ page }) => {
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      const columns = () => feed.evaluate(node => {
        const first = node.querySelector<HTMLElement>('[data-gallery-index="0"]')?.getBoundingClientRect().top
        if (first == null) return 0
        return [...node.querySelectorAll<HTMLElement>('[data-gallery-index]')].filter(tile => Math.round(tile.getBoundingClientRect().top) === Math.round(first)).length
      })
      await expect.poll(columns).toBe(3)
      const area = (await feed.boundingBox())!
      const center = { x: area.x + area.width / 2, y: area.y + area.height / 2 }
      const gestures = await touch(page)
      await gestures.pinch(center, 120, 260)
      await expect.poll(columns).toBe(2)
      await gestures.pinch(center, 240, 100)
      await expect.poll(columns).toBeGreaterThanOrEqual(4)
      const chosen = await columns()
      await page.reload()
      await page.getByRole('button', { name: 'Media', exact: true }).click()
      await page.getByRole('tab', { name: 'All', exact: true }).click()
      await expect.poll(columns).toBe(chosen)
    } finally {
      await closeApp(page, session)
    }
  })

  test('a long press starts selecting, and pinch zooms the details image', async ({ page }) => {
    const session = await bootMixedGallery(page)
    try {
      const feed = page.getByTestId('media-feed')
      await chooseView(page, 'Grid')
      const tile = (await feed.locator('[data-gallery-index="3"]').boundingBox())!
      const gestures = await touch(page)
      await gestures.longPress({ x: tile.x + tile.width / 2, y: tile.y + tile.height / 2 })
      await expect(page.getByRole('toolbar')).toContainText('1 selected')
      await expect(feed.getByRole('checkbox', { name: MIXED[3].name, exact: true })).toHaveAttribute('aria-checked', 'true')
      await page.getByRole('button', { name: 'Done', exact: true }).click()

      await feed.getByRole('button', { name: `Enlarge ${MIXED[3].name}`, exact: true }).tap()
      const zoom = page.getByRole('dialog').getByTestId('zoomable-image')
      await expect(zoom.locator('img')).toHaveJSProperty('complete', true)
      const box = (await zoom.boundingBox())!
      await gestures.pinch({ x: box.x + box.width / 2, y: box.y + box.height / 2 }, 60, 200)
      await expect.poll(async () => Number(await zoom.getAttribute('data-zoom'))).toBeGreaterThan(2)
    } finally {
      await closeApp(page, session)
    }
  })
})
