import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { gotoApp, closeApp } from '../helpers/gotoApp'
import { applyScene3DTemplate } from '../../src/features/scene3d/templates'
import { defaultMediaScreen, parseMediaScreen } from '../../src/features/scene3d/mediaScreen'
import { parseImagePoses } from '../../src/features/scene3d/imagePoseSequence'
import type { Scene3DStageHandle } from '../../src/features/scene3d/Scene3DStage'

for (const media of ['poses', 'video'] as const) {
  test(`a cutout without its still loads and exports its ${media}`, async ({ page }) => {
    const session = await gotoApp(page)
    const scene = applyScene3DTemplate('creative-ocean-window')
    scene.duration = 1
    scene.camera.framing = undefined
    scene.slots = scene.slots.filter(slot => slot.id === 'background')
    const slot = scene.slots[0]
    slot.sourceUrl = ''
    slot.sourceRef = undefined
    const url = `/api/v1/uploads/empty-still.${media === 'video' ? 'webm' : 'png'}`
    const body = await readFile(new URL(media === 'video'
      ? '../../public/rig-previews/animation-jump.webm'
      : '../../public/examples/dark-stillness/wounded-knight.png', import.meta.url))
    let requested = false
    await page.route(`**${url}*`, route => {
      requested = true
      return route.fulfill({ contentType: media === 'video' ? 'video/webm' : 'image/png', body })
    })
    slot.screen = parseMediaScreen({
      ...defaultMediaScreen(), sourceUrl: url, media: media === 'video' ? 'video' : 'image',
      ...(media === 'poses' ? { poseSequence: parseImagePoses([{ sourceUrl: url, duration: 1 }]) } : {}),
    })
    await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
    await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
    const workspace = page.getByTestId('scene3d-workspace')
    await workspace.getByLabel('Open shot JSON').setInputFiles({
      name: 'empty-still.world3d.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(scene)),
    })
    // Exercise the real Stage binding and media decoder. Document-only tests
    // cannot detect an early return before loadScreen runs.
    await page.waitForFunction(slots => {
      const stage = (window as Window & { __world3dStage?: Scene3DStageHandle }).__world3dStage
      return stage?.ready(slots)
    }, scene.slots, { timeout: 15_000 })
    expect(requested).toBe(true)
    await page.route('**/api/v1/scenes/recordings', route => route.fulfill({
      json: { name: 'empty-still.mp4', type: 'video', url: '/api/v1/file/empty-still.mp4' },
    }))
    await workspace.getByTestId('world3d-export').click()
    await expect(workspace.getByTestId('world3d-export-note')).toContainText('empty-still.mp4', { timeout: 30_000 })
    const bytes = await page.evaluate(() => (window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4?.size)
    expect(bytes).toBeGreaterThan(1000)
    await closeApp(page, session)
  })
}
