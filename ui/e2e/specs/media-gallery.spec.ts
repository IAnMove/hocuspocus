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
  const size = type === 'image' ? (index % 2 === 0 ? { width: 480, height: 1600 } : { width: 1600, height: 480 }) : {}
  return { name, type, ...size, mode: type === 'audio' ? 'audio' : 'image', favorite: false, size: 1000,
    created_at: 1_790_000_000 - index, completed_at: 1_790_000_020 - index, completion_time_source: 'metadata',
    url: `/api/v1/file/${name}?workspace=default`, thumbnail_url }
})
const VIEWS = ['One at a time', 'Grid', 'Mosaic'] as const

async function bootMixedGallery(page: Page) {
  const session = await bootGalleryApp(page), fixtures = await installGalleryFixtures(page)
  fixtures.releaseImages(); fixtures.releaseMetadata()
  await page.route('**/api/v1/outputs?*', route => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || MIXED.length)
    return route.fulfill({ json: { outputs: MIXED.slice(offset, offset + limit), total: MIXED.length } })
  })
  await page.route('**/api/v1/file/gallery-*', route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    return name.endsWith('.png') ? route.fulfill({ contentType: 'image/svg+xml', body: svg(name) }) : route.fulfill({ status: 404, body: '' })
  })
  await page.getByRole('button', { name: 'Media', exact: true }).click()
  await page.getByRole('tab', { name: 'All', exact: true }).click()
  return session
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
