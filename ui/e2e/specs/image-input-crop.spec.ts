import { expect, test, type Page } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

async function imageFixture(page: Page) {
  const data = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 400; canvas.height = 300
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = 'red'; ctx.fillRect(0, 0, 200, 300)
    ctx.fillStyle = 'blue'; ctx.fillRect(200, 0, 200, 300)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const original = Buffer.from(data, 'base64'), copies = new Map<string, Buffer>()
  let fail = false
  await page.route('**/api/v1/upload', async route => {
    if (fail) { await route.fulfill({ status: 500, body: 'simulated failure' }); return }
    const body = route.request().postDataBuffer()!
    const start = body.indexOf(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    expect(start).toBeGreaterThanOrEqual(0)
    const bytes = body.subarray(start, body.indexOf(Buffer.from('IEND'), start) + 8)
    const name = `crop-${copies.size + 1}.png`
    copies.set(name, bytes)
    await route.fulfill({ json: { filename: name, path: `/uploads/${name}`, url: `/api/v1/uploads/${name}` } })
  })
  await page.route(/\/api\/v1\/(?:file|uploads|outputs\/thumbnail)\/(?:hero|crop-\d+)\.png(?:\?|$)/, route => {
    const name = new URL(route.request().url()).pathname.split('/').pop()!
    return route.fulfill({ contentType: 'image/png', body: copies.get(name) || original })
  })
  return { original, copies, setFail: (value: boolean) => { fail = value } }
}

test('library crop saves a new input, preserves original pixels, and retries on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript("localStorage.setItem('hocuspocus-wizard-sidebar-collapsed', 'true')")
  const session = await gotoApp(page)
  const fixture = await imageFixture(page)
  try {
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await page.getByRole('tab', { name: 'Tools', exact: true }).click()
    await page.getByRole('button', { name: 'Remove background', exact: true }).click()
    await page.getByRole('button', { name: 'From HocusPocus' }).click()
    const explorer = page.getByRole('dialog').filter({ has: page.getByTestId('asset-explorer') })
    await explorer.locator('button[title="hero.png"]').click()
    await explorer.getByRole('button', { name: 'Choose', exact: true }).click()
    await page.getByRole('button', { name: 'Edit hero.png', exact: true }).click()
    let crop = page.getByRole('dialog', { name: 'Crop image', exact: true })
    await expect(crop.getByLabel('Width (px)')).toHaveValue('400')
    await crop.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(fixture.copies.size).toBe(0)
    await page.getByRole('button', { name: 'Edit hero.png', exact: true }).click()
    crop = page.getByRole('dialog', { name: 'Crop image', exact: true })
    await crop.getByLabel('Left (px)').fill('220')
    await crop.getByLabel('Top (px)').fill('30')
    await crop.getByLabel('Width (px)').fill('100')
    await crop.getByLabel('Height (px)').fill('80')
    fixture.setFail(true)
    await crop.getByRole('button', { name: 'Save crop', exact: true }).click()
    await expect(crop.getByRole('alert')).toContainText('original input is unchanged')
    fixture.setFail(false)
    await crop.getByRole('button', { name: 'Save crop', exact: true }).click()
    await expect(crop).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit crop-1.png', exact: true })).toBeVisible()
    expect(fixture.copies.size).toBe(1)
    const cropped = fixture.copies.get('crop-1.png')!
    expect([cropped.readUInt32BE(16), cropped.readUInt32BE(20)]).toEqual([100, 80])
    expect([fixture.original.readUInt32BE(16), fixture.original.readUInt32BE(20)]).toEqual([400, 300])
    const pixel = await page.evaluate(async () => {
      const image = new Image(); image.src = '/api/v1/uploads/crop-1.png'; await image.decode()
      const canvas = document.createElement('canvas'); const ctx = canvas.getContext('2d')!
      ctx.drawImage(image, 0, 0)
      return [...ctx.getImageData(0, 0, 1, 1).data]
    })
    expect(pixel).toEqual([0, 0, 255, 255])
  } finally { await closeApp(page, session) }
})

test('each locally imported batch image has a preview and cropping replaces only that image', async ({ page }) => {
  const session = await gotoApp(page)
  const fixture = await imageFixture(page)
  await page.route('**/api/v1/models', route => route.fulfill({ json: { families: [{ id: 'qwen', label: 'Qwen', order: 1 }], models: [{ model_type: 'qwen_image_21', name: 'Qwen', family: 'qwen', architecture: 'qwen_image_21', is_downloaded: true, is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 1 }] } }))
  await page.route('**/api/v1/model-visibility', route => route.fulfill({ json: { configured: true, enabled_models: ['qwen_image_21'], initialized_mature_models: [], defaults_version: 9 } }))
  await page.route('**/api/v1/model-options/*', route => route.fulfill({ json: { image_source_support: true, image_outputs: true } }))
  try {
    await page.reload()
    await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
    await page.getByRole('tab', { name: 'Image', exact: true }).click()
    await page.getByRole('button', { name: /Edit image/ }).click()
    await page.getByRole('checkbox', { name: 'Edit multiple images separately' }).check()
    await page.getByTestId('image-batch-files').setInputFiles(['one', 'two'].map(name => ({ name: `${name}.png`, mimeType: 'image/png', buffer: fixture.original })))
    await expect(page.getByRole('img', { name: 'one.png', exact: true })).toBeVisible()
    await expect(page.getByRole('img', { name: 'two.png', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Edit one.png', exact: true }).click()
    const crop = page.getByRole('dialog', { name: 'Crop image', exact: true })
    await expect(crop.getByLabel('Width (px)')).toHaveValue('400')
    const surface = await crop.getByTestId('crop-surface').boundingBox()
    await page.mouse.move(surface!.x + surface!.width * .25, surface!.y + surface!.height * .25)
    await page.mouse.down()
    await page.mouse.move(surface!.x + surface!.width * .75, surface!.y + surface!.height * .75)
    await page.mouse.up()
    expect(Math.abs(Number(await crop.getByLabel('Width (px)').inputValue()) - 200)).toBeLessThanOrEqual(1)
    expect(Math.abs(Number(await crop.getByLabel('Height (px)').inputValue()) - 150)).toBeLessThanOrEqual(1)
    await crop.getByLabel('Width (px)').fill('120')
    await crop.getByLabel('Height (px)').fill('90')
    await crop.getByRole('button', { name: 'Save crop', exact: true }).click()
    await expect(crop).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit crop-1.png', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit two.png', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit one.png', exact: true })).toHaveCount(0)
    expect(fixture.copies.size).toBe(1)
  } finally { await closeApp(page, session) }
})
