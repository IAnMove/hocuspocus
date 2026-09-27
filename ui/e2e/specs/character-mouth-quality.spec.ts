import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'
import { createCharacterKit, type CharacterKitLibrary } from '../../src/lib/characterKit'

test('nine-mouth style saves a resting still and exports the shareable collection', async ({ page }) => {
  const session = await gotoApp(page)
  const baseImage = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256
    const context = canvas.getContext('2d')!; context.fillStyle = '#aaaaaa'; context.fillRect(0, 0, 256, 256)
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  const kit = createCharacterKit('Resting face fixture')
  kit.base = { id: 'base', name: 'Mouthless base', source: '/mouth-quality-base.png', kind: 'image', reviewState: 'approved', alphaStatus: 'opaque' }
  kit.identityReference = { ...kit.base }
  kit.anchors.base = { mouth: { offsetX: 0, offsetY: 0, scale: .6, rotation: 0 } }
  let library: CharacterKitLibrary = { version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } }
  let restingImage: Buffer | undefined
  await page.route('**/mouth-quality-base.png', route => route.fulfill({ contentType: 'image/png', body: baseImage }))
  await page.route('**/mouth-quality-rest.png', route => route.fulfill({ contentType: 'image/png', body: restingImage! }))
  await page.route('**/api/v1/upload', async route => {
    const request = route.request()
    const body = await new Request('http://test/upload', { method: 'POST', headers: { 'Content-Type': (await request.headerValue('content-type'))! }, body: request.postDataBuffer()! }).formData()
    const file = body.get('file') as File
    restingImage = Buffer.from(await file.arrayBuffer())
    await route.fulfill({ json: { url: '/mouth-quality-rest.png', filename: 'mouth-quality-rest.png', path: 'mouth-quality-rest.png' } })
  })
  await page.route('**/api/v1/character-kits/library**', async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      expect(body.baseRevision).toBe(1)
      expect(body.kit.base).toEqual(kit.base)
      expect(Object.keys(body.kit.mouth)).toHaveLength(9)
      expect(Object.values(body.kit.mouth).every((asset) => (asset as { reviewState: string }).reviewState === 'pending')).toBe(true)
      expect(body.kit.restPose.asset.source).toBe('/mouth-quality-rest.png')
      expect(body.kit.restPose.asset.reviewState).toBe('pending')
      library = { ...library, revision: 2, kits: { [kit.id]: body.kit } }
    }
    await route.fulfill({ json: library })
  })
  await page.getByRole('tab', { name: 'Character Creator', exact: true }).click()
  await page.locator('summary').filter({ hasText: 'Prepare 2D speech' }).click()
  const workshop = page.getByRole('region', { name: 'Prepare 2D speech', exact: true })
  await workshop.getByRole('combobox', { name: 'Mouth style pack' }).selectOption('ruby-ink')
  await expect(workshop.getByRole('region', { name: 'Existing mouths' }).locator('figure')).toHaveCount(9)
  await workshop.getByRole('button', { name: 'Use pack', exact: true }).click()
  await workshop.getByRole('button', { name: 'Save speech character', exact: true }).click()
  await expect(workshop.getByText(/Character saved to this workspace/)).toBeVisible()
  expect(restingImage).toBeDefined()
  const pixels = await page.evaluate(async base64 => {
    const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${base64}`)).blob())
    const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height
    const context = canvas.getContext('2d')!; context.drawImage(bitmap, 0, 0); bitmap.close()
    return { center: [...context.getImageData(128, 128, 1, 1).data], corner: [...context.getImageData(10, 10, 1, 1).data] }
  }, restingImage!.toString('base64'))
  expect(pixels.corner).toEqual([170, 170, 170, 255])
  expect(pixels.center).not.toEqual(pixels.corner)
  const downloadPromise = page.waitForEvent('download')
  await workshop.getByRole('button', { name: 'Download the 20 new styles', exact: true }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('hocuspocus-20-mouth-styles.zip')
  expect(await download.failure()).toBeNull()
  await closeApp(page, session)
})
